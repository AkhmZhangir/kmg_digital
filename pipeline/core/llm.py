"""Клиент LLM: любой OpenAI-совместимый chat/completions (Qwen на своём сервере, Gemini, DeepSeek)
или офлайн-заглушка `mock`. Ответы кешируются на диск по хешу запроса.

Настройки — переменные окружения или файл pipeline/.env:
  LLM_BASE_URL   http://host:8000/v1   |  https://generativelanguage.googleapis.com/v1beta/openai  |  mock
  LLM_MODEL      имя модели на сервере
  LLM_API_KEY    ключ, если нужен
  LLM_TIMEOUT    секунды (по умолчанию 300)
  LLM_JSON_MODE  1 — передавать response_format=json_object (по умолчанию 1)
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CACHE = HERE / ".cache" / "llm"
USAGE_LOG = HERE / ".cache" / "usage.jsonl"


def load_env(path: Path = HERE / ".env") -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class LLMError(RuntimeError):
    pass


def extract_json(text: str):
    """JSON из ответа модели: убирает <think>, ```json-ограждения, берёт внешний объект."""
    text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
    fence = re.search(r"(?s)```(?:json)?\s*(.*?)```", text)
    if fence:
        text = fence.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise LLMError("В ответе нет JSON")
    depth, in_str, esc = 0, False, False
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            elif ch != "\\":
                esc = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise LLMError("JSON в ответе оборван")


class LLM:
    def __init__(self, base_url=None, model=None, api_key=None, label="main"):
        load_env()
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "mock")).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "mock")
        self.api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
        self.timeout = int(os.getenv("LLM_TIMEOUT", "300"))
        self.json_mode = os.getenv("LLM_JSON_MODE", "1") == "1"
        self.label = label
        self.calls = 0
        self.cache_hits = 0
        if self.is_mock:
            from . import mock
            self._mock = mock

    @property
    def is_mock(self) -> bool:
        return self.base_url == "mock"

    @property
    def name(self) -> str:
        return "mock" if self.is_mock else self.model

    def _key(self, messages, temperature):
        blob = json.dumps([self.model, messages, temperature], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def chat_json(self, system: str, payload: dict, temperature: float = 0.2, task: str = "") -> dict:
        """Отправляет system + payload (JSON) и возвращает разобранный JSON-ответ. Кеширует."""
        user = json.dumps(payload, ensure_ascii=False)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.is_mock:  # заглушку не кешируем
            self.calls += 1
            return self._mock.respond(task, payload)
        key = self._key(messages, temperature)
        path = CACHE / f"{key}.json"
        if path.is_file():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["parsed"]
        t0 = time.monotonic()
        if self.is_mock:
            parsed, raw, usage = self._mock.respond(task, payload), "", {}
        else:
            raw, usage = self._post(messages, temperature)
            parsed = extract_json(raw)
        self.calls += 1
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"task": task, "model": self.name, "raw": raw, "parsed": parsed},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        with USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "task": task, "model": self.name, "seconds": round(time.monotonic() - t0, 2),
                                **{k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")}}) + "\n")
        return parsed

    def _post(self, messages, temperature):
        body = {"model": self.model, "messages": messages, "temperature": temperature}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        url = self.base_url + "/chat/completions"
        delay = 5
        for attempt in range(6):
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.load(r)
                return data["choices"][0]["message"]["content"] or "", data.get("usage") or {}
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code == 400 and self.json_mode and "response_format" in detail:
                    body.pop("response_format", None)  # сервер не умеет json_object
                    continue
                if e.code in (408, 429, 500, 502, 503, 504) and attempt < 5:
                    time.sleep(delay)
                    delay = min(delay * 2, 90)
                    continue
                raise LLMError(f"HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 5:
                    time.sleep(delay)
                    delay = min(delay * 2, 90)
                    continue
                raise LLMError(f"Нет связи с {url}: {e}") from e
        raise LLMError("Исчерпаны попытки")
