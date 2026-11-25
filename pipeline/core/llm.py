"""Клиент LLM: любой OpenAI-совместимый chat/completions (Qwen на своём сервере, Gemini, DeepSeek)
или офлайн-заглушка `mock`. Ответы кешируются на диск по хешу запроса.

Настройки — переменные окружения или файл pipeline/.env:
  LLM_BASE_URL   http://host:8000/v1   |  https://generativelanguage.googleapis.com/v1beta/openai  |  mock
  LLM_MODEL      имя модели на сервере
  LLM_API_KEY    ключ, если нужен
  LLM_TIMEOUT    секунды (по умолчанию 300)
  LLM_JSON_MODE  1 — передавать response_format=json_object (по умолчанию 1)
  LLM_MAX_TOKENS предел длины ответа (для llama.cpp полезно 8192)
  LLM_NO_THINK   1 — выключить режим рассуждений Qwen3 (chat_template_kwargs.enable_thinking=false)
  LLM_PARALLEL   сколько запросов одновременно (llama.cpp с одним слотом — 1)
Профиль можно держать в отдельном файле и выбирать флагом: py -3 run.py all --env .env.qwen ...
"""
import hashlib
import json
import os
import re
import threading
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


_LATEX_BS = re.compile(r'\\\\|\\(?=[bfnrt][a-zA-Z])|\\(?=u(?![0-9a-fA-F]{4}))|\\(?![\\"/bfnrtu])')


def fix_latex_escapes(s: str) -> str:
    r"""LaTeX внутри JSON-строк: \rho, \frac, \( — не JSON-escape. \frac и \times JSON прочитал бы как \f и \t.
    Уже экранированные пары \\ не трогаем."""
    return _LATEX_BS.sub(lambda m: m.group(0) if m.group(0) == "\\\\" else "\\\\", s)


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
                chunk = text[start:i + 1]
                try:
                    return json.loads(fix_latex_escapes(chunk))
                except json.JSONDecodeError:
                    return json.loads(chunk)
    raise LLMError("JSON в ответе оборван")


class LLM:
    """LLM_MODEL может быть списком через запятую: при исчерпании дневной квоты (429 PerDay) или
    перегрузке модели (503) клиент переходит к следующей. Кеш не зависит от модели — пересборка не тратит запросов."""

    def __init__(self, base_url=None, model=None, api_key=None, label="main"):
        load_env()
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "mock")).rstrip("/")
        self.models = [m.strip() for m in (model or os.getenv("LLM_MODEL", "mock")).split(",") if m.strip()]
        self.active = 0
        self.api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
        self.timeout = int(os.getenv("LLM_TIMEOUT", "300"))
        self.json_mode = os.getenv("LLM_JSON_MODE", "1") == "1"
        self.label = label
        self.calls = 0
        self.cache_hits = 0
        self.used = {}
        self._lock = threading.Lock()
        if self.is_mock:
            from . import mock
            self._mock = mock

    @property
    def is_mock(self) -> bool:
        return self.base_url == "mock"

    @property
    def model(self) -> str:
        return self.models[min(self.active, len(self.models) - 1)]

    @property
    def name(self) -> str:
        if self.is_mock:
            return "mock"
        return "+".join(sorted(self.used, key=lambda m: -self.used[m])) if self.used else self.model

    @staticmethod
    def _hash(obj) -> str:
        return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]

    def chat_json(self, system: str, payload: dict, temperature: float = 0.2, task: str = "") -> dict:
        """Отправляет system + payload (JSON) и возвращает разобранный JSON-ответ. Кеширует."""
        user = json.dumps(payload, ensure_ascii=False)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.is_mock:  # заглушку не кешируем
            self.calls += 1
            return self._mock.respond(task, payload)
        # Кеш общий для моделей одного сервера, но не для разных серверов (иначе Qwen получил бы ответы Gemini).
        key = self._hash([self.base_url, messages, temperature])
        legacy = [self._hash([messages, temperature])] + [self._hash([m, messages, temperature]) for m in self.models]
        for k in [key] + legacy:
            path = CACHE / f"{k}.json"
            if path.is_file():
                entry = json.loads(path.read_text(encoding="utf-8"))
                base = entry.get("base") or ("https://generativelanguage.googleapis.com/v1beta/openai"
                                             if str(entry.get("model", "")).startswith("gemini") else "")
                if base.rstrip("/") == self.base_url:
                    self.cache_hits += 1
                    return entry["parsed"]
        path = CACHE / f"{key}.json"
        t0 = time.monotonic()
        raw, usage, model = self._post(messages, temperature)
        parsed = extract_json(raw)
        with self._lock:
            self.calls += 1
            self.used[model] = self.used.get(model, 0) + 1
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"task": task, "model": model, "base": self.base_url, "raw": raw, "parsed": parsed},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        with self._lock, USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "task": task, "model": model, "seconds": round(time.monotonic() - t0, 2),
                                **{k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")}}) + "\n")
        return parsed

    def _next_model(self, failed: str, why: str) -> bool:
        with self._lock:
            if self.model == failed and self.active < len(self.models) - 1:
                self.active += 1
                print(f"  LLM: {failed} — {why}; переключаюсь на {self.model}", flush=True)
            return self.model != failed

    def _post(self, messages, temperature):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        url = self.base_url + "/chat/completions"
        json_mode, delay = self.json_mode, 5
        for attempt in range(8):
            model = self.model
            body = {"model": model, "messages": messages, "temperature": temperature}
            if os.getenv("LLM_MAX_TOKENS"):
                body["max_tokens"] = int(os.environ["LLM_MAX_TOKENS"])
            if os.getenv("LLM_NO_THINK") == "1":  # Qwen3 / llama.cpp: без длинных рассуждений <think>
                body["chat_template_kwargs"] = {"enable_thinking": False}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.load(r)
                return data["choices"][0]["message"]["content"] or "", data.get("usage") or {}, model
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:4000]
                if e.code == 400 and json_mode and "response_format" in detail:
                    json_mode = False  # сервер не умеет json_object
                    continue
                if e.code == 429 and "PerDay" in detail and self._next_model(model, "дневная квота исчерпана"):
                    continue
                if e.code in (404, 503) and attempt >= 1 and self._next_model(model, f"HTTP {e.code}"):
                    continue
                if e.code in (408, 429, 500, 502, 503, 504) and attempt < 7:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise LLMError(f"HTTP {e.code} ({model}): {detail[:400]}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < 7:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise LLMError(f"Нет связи с {url}: {e}") from e
        raise LLMError("Исчерпаны попытки")
