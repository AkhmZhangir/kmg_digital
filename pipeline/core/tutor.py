"""Тьютор для вкладки «Чаты»: поиск выдержек по источникам → модель → проверка цитат.

Источники:
  - глава, собранная run.py (out/<папка>/layer.json + units.json), id = layer.chapter.id (например "latyshova");
  - текст, загруженный через POST /api/sources (txt/md), id = "src-<хеш>".
Цитаты проверяются детерминированно (textnorm.quote_match) — непроверенные выкидываются.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

from .textnorm import quote_match

HERE = Path(__file__).resolve().parent.parent
PROMPT = (HERE / "prompts" / "tutor.txt").read_text(encoding="utf-8")
MODES = ("ask", "learn", "practice", "review")
CONTEXT_CHARS = 9000      # ≈3k токенов: влезает и в 16k-слот Qwen
HISTORY_TURNS = 6
MAX_MESSAGE = 4000


class TutorError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)
_STOP = set("и в во на по с со к ко о об от до из за для при как что это то так же ли не ни а но или у его ее её их мы вы он она они "
            "the of and to in is are a an".split())


def _stems(text: str) -> set[str]:
    return {w[:6] for w in _WORD.findall(text.lower().replace("ё", "е")) if len(w) > 2 and w not in _STOP}


CHUNK = 1200  # знаков на единицу загруженного файла: поиск точнее, а текст не обрезается


def _chunks(body: str) -> list[str]:
    """Абзацы по пустым строкам; длинный абзац (обычный TXT без пустых строк) — по строкам, затем по предложениям.
    Ничего не отбрасывается, кроме пустых и совсем коротких обрывков."""
    out = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= CHUNK:
            pieces = [para]
        else:
            pieces, cur = [], ""
            for line in re.split(r"\n|(?<=[.!?])\s+", para):
                line = line.strip()
                while len(line) > CHUNK:  # строка без переносов и точек
                    pieces.append(line[:CHUNK])
                    line = line[CHUNK:]
                if cur and len(cur) + len(line) + 1 > CHUNK:
                    pieces.append(cur)
                    cur = ""
                cur = (cur + "\n" + line).strip()
            if cur:
                pieces.append(cur)
        out += [p for p in pieces if len(p) >= 20 or (p and not out)]
    return out


class Source:
    def __init__(self, sid: str, name: str, units: list[dict], layer: dict | None = None, folder: Path | None = None):
        self.id, self.name, self.units, self.layer, self.folder = sid, name, units, layer, folder
        self.by_id = {u["id"]: u for u in units}
        self.stems = {u["id"]: _stems(u["text"]) for u in units}
        self.nodes = {n["id"]: n for n in (layer or {}).get("nodes", [])}

    def meta(self) -> dict:
        ch = (self.layer or {}).get("chapter", {})
        pages = ch.get("pages") or [min(u["page"] for u in self.units), max(u["page"] for u in self.units)]
        return {"id": self.id, "name": self.name, "kind": "chapter" if self.layer else "upload",
                "units": len(self.units), "pages": pages, "nodes": len(self.nodes),
                "folder": self.folder.name if self.folder else None}


class Library:
    """Все источники, доступные чату. Главы читаются из out/*/layer.json."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.sources: dict[str, Source] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self):
        for layer_path in sorted(self.out_dir.glob("*/layer.json")):
            units_path = layer_path.with_name("units.json")
            if not units_path.is_file():
                continue
            layer = json.loads(layer_path.read_text(encoding="utf-8"))
            units = [u for u in json.loads(units_path.read_text(encoding="utf-8")) if u.get("kind") != "heading"]
            ch = layer.get("chapter", {})
            src = Source(ch.get("id") or layer_path.parent.name, ch.get("book") or layer_path.parent.name,
                         units, layer, layer_path.parent)
            with self._lock:
                self.sources[src.id] = src
                self.sources.setdefault(layer_path.parent.name, src)  # и по имени папки: train_latyshova

    def add_text(self, name: str, text: str) -> Source:
        text = text.replace("\r\n", "\n").strip()
        if not text:
            raise TutorError(400, "empty_source", "Файл пустой")
        sid = "src-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        units = []
        # Метки <!-- page N --> — в любом месте текста; без меток весь файл = страница 1.
        parts = re.split(r"<!--\s*page\s+(\d+)\s*-->", text)
        pages = [(1, parts[0])] + [(int(n), body) for n, body in zip(parts[1::2], parts[2::2])]
        for page, body in pages:
            for chunk in _chunks(body):
                units.append({"id": f"{sid}.u{len(units) + 1:03d}", "page": page, "text": chunk})
        if not units:
            raise TutorError(400, "empty_source", "В файле нет абзацев текста")
        src = Source(sid, name, units)
        with self._lock:
            self.sources[sid] = src
        return src

    def get(self, sid: str) -> Source:
        src = self.sources.get(sid)
        if not src:
            raise TutorError(404, "unknown_source", f"Источник не найден: {sid}")
        return src

    def list(self) -> list[dict]:
        seen, out = set(), []
        for s in self.sources.values():
            if id(s) not in seen:
                seen.add(id(s))
                out.append(s.meta())
        return out


def _retrieve(sources: list[Source], query: str, lesson: str | None) -> list[tuple[Source, dict]]:
    """Лексический поиск: пересечение основ слов + бонус абзацам текущего урока."""
    q = _stems(query)
    scored = []
    for src in sources:
        lesson_units = set(src.nodes[lesson]["units"]) if lesson in src.nodes else set()
        for u in src.units:
            s = len(q & src.stems[u["id"]]) / (1 + len(q)) ** 0.5
            if u["id"] in lesson_units:
                s += 0.8
            if s > 0:
                scored.append((s, src, u))
    scored.sort(key=lambda t: -t[0])
    picked, size = [], 0
    for _, src, u in scored:
        if size + len(u["text"]) > CONTEXT_CHARS and picked:
            continue
        picked.append((src, u))
        size += len(u["text"])
        if size >= CONTEXT_CHARS:
            break
    picked.sort(key=lambda t: (t[0].id, t[1].get("page") or 0, t[1]["id"]))
    return picked


def _lesson_info(sources: list[Source], lesson: str | None) -> dict | None:
    for src in sources:
        n = src.nodes.get(lesson or "")
        if n:
            return {"id": n["id"], "title": n["title"], "pages": n.get("pages"),
                    "summary": [p["text"] for p in n.get("summary", [])][:4]}
    return None


def _clean_history(history) -> list[dict]:
    out = []
    for h in (history or [])[-HISTORY_TURNS:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("text"), str):
            out.append({"role": h["role"], "text": h["text"][:1500]})
    return out


def chat(lib: Library, llm, req: dict) -> dict:
    if not isinstance(req, dict):
        raise TutorError(400, "bad_request", "Ожидается JSON-объект")
    message = (req.get("message") or "").strip()
    if not message:
        raise TutorError(400, "empty_message", "Пустой вопрос")
    if len(message) > MAX_MESSAGE:
        raise TutorError(400, "message_too_long", f"Вопрос длиннее {MAX_MESSAGE} символов")
    mode = req.get("mode") or "ask"
    if mode not in MODES:
        raise TutorError(400, "bad_mode", f"mode должен быть одним из {', '.join(MODES)}")
    ids = req.get("sources") or []
    if not ids:
        raise TutorError(400, "no_sources", "Не выбран ни один источник")
    sources = [lib.get(s) for s in ids]
    lesson = req.get("lesson")
    history = _clean_history(req.get("history"))

    query = message + " " + " ".join(h["text"] for h in history if h["role"] == "user")[-500:]
    picked = _retrieve(sources, query, lesson)
    refs = {}
    context = []
    for i, (src, u) in enumerate(picked, 1):
        ref = f"r{i}"
        refs[ref] = (src, u)
        context.append({"id": ref, "source": src.name, "page": u.get("page"), "text": u["text"]})

    if not context:
        return {"answer": "В выбранных источниках не нашлось ничего по этому вопросу. Попробуй переформулировать "
                          "или выбери другой источник.",
                "citations": [], "insufficient": True, "task": None, "followups": [], "mode": mode,
                "model": None, "context_used": 0}

    payload = {"mode": mode, "lesson": _lesson_info(sources, lesson), "history": history,
               "question": message, "context": context}
    try:
        res = llm.chat_json(PROMPT, payload, temperature=0.3, task="tutor")
    except Exception as e:  # LLMError, нет связи, кривой JSON
        raise TutorError(503, "model_unavailable", f"Модель недоступна: {e}") from None
    if not isinstance(res, dict):
        raise TutorError(502, "bad_model_answer", "Модель вернула не JSON-объект")

    citations, dropped = [], 0
    for c in res.get("citations") or []:
        if not isinstance(c, dict) or c.get("ref") not in refs:
            dropped += 1
            continue
        src, u = refs[c["ref"]]
        quote = (c.get("quote") or "").strip()
        how, _ = quote_match(quote, u["text"])
        if how == "none":
            dropped += 1
            continue
        citations.append({"source_id": src.id, "source": src.name, "unit": u["id"], "page": u.get("page"),
                          "quote": quote, "match": how})

    answer = (res.get("answer") or "").strip()
    insufficient = bool(res.get("insufficient"))
    if not answer:
        raise TutorError(502, "bad_model_answer", "Модель вернула пустой ответ")
    task = res.get("task") if mode == "practice" and isinstance(res.get("task"), dict) else None
    if task and task.get("ref") in refs:
        src, u = refs[task["ref"]]
        task = {"question": task.get("question"), "answer": task.get("answer"),
                "source_id": src.id, "page": u.get("page"), "unit": u["id"]}
    elif task:
        task = {"question": task.get("question"), "answer": task.get("answer"), "source_id": None, "page": None,
                "unit": None}
    return {"answer": answer, "citations": citations, "insufficient": insufficient,
            "unverified": not citations and not insufficient, "dropped_citations": dropped,
            "task": task, "followups": [f for f in (res.get("followups") or []) if isinstance(f, str)][:3],
            "mode": mode, "model": llm.name, "context_used": len(context)}
