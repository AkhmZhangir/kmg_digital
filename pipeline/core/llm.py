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
Профили моделей: файлы .env.<имя> и цепочка LLM_PROFILES=gemini,qwen (или run.py --llm gemini,qwen):
когда у Gemini кончаются дневные квоты или пропадает связь, работа продолжается на следующем профиле.
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


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def read_profile(name: str) -> dict:
    """Профиль модели: pipeline/.env.<name> (KEY=VALUE). 'mock' — офлайн-заглушка без файла."""
    if name == "mock":
        return {"LLM_BASE_URL": "mock", "LLM_MODEL": "mock"}
    path = HERE / f".env.{name}"
    if not path.is_file():
        raise LLMError(f"Нет профиля модели {path.name} (скопируйте .env.example)")
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class Provider:
    """Один сервер (Gemini, Qwen на llama.cpp, DeepSeek…) со списком моделей и своим пределом параллельности."""

    def __init__(self, name: str, cfg: dict):
        get = lambda k, d="": cfg.get(k, d)
        self.name = name
        self.base_url = get("LLM_BASE_URL", "mock").rstrip("/")
        self.models = [m.strip() for m in get("LLM_MODEL", "mock").split(",") if m.strip()]
        self.active = 0
        self.api_key = get("LLM_API_KEY")
        self.timeout = int(get("LLM_TIMEOUT", "300"))
        self.json_mode = get("LLM_JSON_MODE", "1") == "1"
        self.max_tokens = int(get("LLM_MAX_TOKENS", "0") or 0)
        self.no_think = get("LLM_NO_THINK") == "1"
        self.parallel = max(1, int(get("LLM_PARALLEL", "4")))
        self.slots = threading.BoundedSemaphore(self.parallel)
        self.dead = False

    @property
    def model(self) -> str:
        return self.models[min(self.active, len(self.models) - 1)]

    @property
    def is_mock(self) -> bool:
        return self.base_url == "mock"


class LLM:
    """Клиент с цепочкой провайдеров.

    Профили: LLM_PROFILES=gemini,qwen (или run.py --llm gemini,qwen) — файлы pipeline/.env.gemini, .env.qwen.
    Внутри провайдера LLM_MODEL может быть списком моделей. Переход дальше по цепочке:
      модель исчерпала дневную квоту (429 PerDay) или перегружена (503/404) → следующая модель провайдера;
      у провайдера кончились модели или нет связи (туннель упал) → следующий провайдер.
    Без LLM_PROFILES работает старый режим: один провайдер из переменных LLM_* (.env).
    Кеш ответов привязан к адресу сервера; при пересборке годится ответ любого провайдера цепочки.
    """

    def __init__(self, profiles: str | None = None):
        load_env()
        names = [p.strip() for p in (profiles or os.getenv("LLM_PROFILES", "")).split(",") if p.strip()]
        if names:
            self.providers = [Provider(n, read_profile(n)) for n in names]
        else:
            self.providers = [Provider("env", {k: v for k, v in os.environ.items() if k.startswith("LLM_")})]
        self.p = 0
        self.calls = 0
        self.cache_hits = 0
        self.used = {}
        self._lock = threading.Lock()
        if self.is_mock:
            from . import mock
            self._mock = mock

    # -- текущий провайдер
    @property
    def cur(self) -> Provider:
        return self.providers[min(self.p, len(self.providers) - 1)]

    @property
    def is_mock(self) -> bool:
        return self.cur.is_mock

    @property
    def base_url(self) -> str:
        return self.cur.base_url

    @property
    def model(self) -> str:
        return self.cur.model

    @property
    def parallel(self) -> int:
        return max(p.parallel for p in self.providers)

    @property
    def name(self) -> str:
        if self.is_mock:
            return "mock"
        return "+".join(sorted(self.used, key=lambda m: -self.used[m])) if self.used else self.model

    @staticmethod
    def _hash(obj) -> str:
        return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]

    def _cached(self, messages, temperature):
        bases = {p.base_url for p in self.providers}
        keys = [self._hash([p.base_url, messages, temperature]) for p in self.providers]
        keys += [self._hash([messages, temperature])]
        keys += [self._hash([m, messages, temperature]) for p in self.providers for m in p.models]
        for k in keys:
            path = CACHE / f"{k}.json"
            if path.is_file():
                entry = json.loads(path.read_text(encoding="utf-8"))
                base = entry.get("base") or (GEMINI_BASE if str(entry.get("model", "")).startswith("gemini") else "")
                if base.rstrip("/") in bases:
                    return entry
        return None

    def chat_json(self, system: str, payload: dict, temperature: float = 0.2, task: str = "") -> dict:
        """Отправляет system + payload (JSON) и возвращает разобранный JSON-ответ. Кеширует."""
        user = json.dumps(payload, ensure_ascii=False)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.is_mock:  # заглушку не кешируем
            self.calls += 1
            return self._mock_respond(task, payload)
        hit = self._cached(messages, temperature)
        if hit:
            self.cache_hits += 1
            return hit["parsed"]
        t0 = time.monotonic()
        res = self._post(messages, temperature)
        if res is None:  # цепочка дошла до заглушки mock
            self.calls += 1
            return self._mock_respond(task, payload)
        raw, usage, model, prov = res
        parsed = extract_json(raw)
        with self._lock:
            self.calls += 1
            self.used[model] = self.used.get(model, 0) + 1
        path = CACHE / f"{self._hash([prov.base_url, messages, temperature])}.json"
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"task": task, "model": model, "base": prov.base_url, "raw": raw, "parsed": parsed},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        with self._lock, USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "task": task, "model": model, "provider": prov.name,
                                "seconds": round(time.monotonic() - t0, 2),
                                **{k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")}}) + "\n")
        return parsed

    def _mock_respond(self, task, payload):
        from . import mock
        return mock.respond(task, payload)

    # -- переключения
    def _next_model(self, prov: Provider, failed: str, why: str) -> bool:
        with self._lock:
            if prov.model == failed and prov.active < len(prov.models) - 1:
                prov.active += 1
                print(f"  LLM[{prov.name}]: {failed} — {why}; переключаюсь на {prov.model}", flush=True)
            return prov.model != failed

    def _next_provider(self, prov: Provider, why: str) -> bool:
        with self._lock:
            prov.dead = True
            if self.cur is prov and self.p < len(self.providers) - 1:
                self.p += 1
                print(f"  LLM: {prov.name} недоступен ({why}); переключаюсь на {self.cur.name} ({self.cur.model})", flush=True)
            return not self.cur.dead

    def _post(self, messages, temperature):
        while True:
            prov = self.cur
            if prov.is_mock:
                return None
            try:
                with prov.slots:
                    raw, usage, model = self._post_one(prov, messages, temperature)
                return raw, usage, model, prov
            except _ProviderDown as e:
                if not self._next_provider(prov, str(e)):
                    raise LLMError(f"Все провайдеры цепочки недоступны: {e}") from None

    def _post_one(self, prov: Provider, messages, temperature):
        headers = {"Content-Type": "application/json"}
        if prov.api_key:
            headers["Authorization"] = "Bearer " + prov.api_key
        url = prov.base_url + "/chat/completions"
        json_mode, delay = prov.json_mode, 5
        for attempt in range(8):
            model = prov.model
            body = {"model": model, "messages": messages, "temperature": temperature}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            if prov.max_tokens:
                body["max_tokens"] = prov.max_tokens
            if prov.no_think:  # Qwen3 / llama.cpp: без длинных рассуждений <think>
                body["chat_template_kwargs"] = {"enable_thinking": False}
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=prov.timeout) as r:
                    data = json.load(r)
                return data["choices"][0]["message"]["content"] or "", data.get("usage") or {}, model
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:4000]
                if e.code == 400 and json_mode and "response_format" in detail:
                    json_mode = False  # сервер не умеет json_object
                    continue
                if e.code == 429 and "PerDay" in detail:
                    if self._next_model(prov, model, "дневная квота исчерпана"):
                        continue
                    raise _ProviderDown("дневные квоты всех моделей исчерпаны")
                if e.code in (404, 503) and attempt >= 1:
                    if self._next_model(prov, model, f"HTTP {e.code}"):
                        continue
                    if attempt >= 3:
                        raise _ProviderDown(f"HTTP {e.code}")
                if e.code in (401, 403):
                    raise _ProviderDown(f"HTTP {e.code}: нет доступа")
                if e.code in (408, 429, 500, 502, 503, 504) and attempt < 7:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise LLMError(f"HTTP {e.code} ({model}): {detail[:400]}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < 3:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise _ProviderDown(f"нет связи с {url}: {e}") from None
        raise _ProviderDown("исчерпаны попытки")


class _ProviderDown(Exception):
    pass


def probe(profile: str, models: list[str] | None = None) -> list[dict]:
    """Проверка доступности: по одному крошечному запросу (max_tokens=1) к каждой модели профиля."""
    prov = Provider(profile, read_profile(profile))
    out = []
    for m in models or prov.models:
        body = {"model": m, "messages": [{"role": "user", "content": "1"}], "max_tokens": 1}
        if prov.no_think:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        headers = {"Content-Type": "application/json"}
        if prov.api_key:
            headers["Authorization"] = "Bearer " + prov.api_key
        req = urllib.request.Request(prov.base_url + "/chat/completions", data=json.dumps(body).encode("utf-8"), headers=headers)
        t0 = time.monotonic()
        row = {"profile": profile, "model": m}
        try:
            urllib.request.urlopen(req, timeout=60).read()
            row["status"] = "доступна"
        except urllib.error.HTTPError as e:
            d = e.read().decode("utf-8", "replace")
            lim = re.search(r'"quotaValue":\s*"(\d+)"', d)
            kind = "в сутки" if "PerDay" in d else ("в минуту" if "PerMinute" in d else "")
            row["status"] = {429: "лимит исчерпан", 503: "перегружена", 404: "недоступна"}.get(e.code, f"HTTP {e.code}")
            if lim:
                row["limit"] = f"{lim.group(1)} {kind}".strip()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            row["status"] = f"нет ответа ({type(e).__name__})"
        row["seconds"] = round(time.monotonic() - t0, 1)
        out.append(row)
    return out


def usage_today() -> dict:
    """Сколько запросов к каждой модели за последние 24 часа (по журналу .cache/usage.jsonl)."""
    out = {}
    if USAGE_LOG.is_file():
        now = time.time()
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("model") != "mock" and now - r["t"] < 86400:
                    out[r["model"]] = out.get(r["model"], 0) + 1
    return out
