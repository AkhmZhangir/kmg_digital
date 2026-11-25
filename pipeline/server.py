"""Сервер тьютора: API чата + раздача собранных курсов из out/.

  cd pipeline
  $env:PYTHONUTF8=1; py -3 server.py                 # модели из LLM_PROFILES (.env), порт 8770
  py -3 server.py --llm mock --port 8770             # без модели (заглушка) — для фронтенда
  py -3 server.py --llm qwen --out out_qwen

Открыть курс: http://127.0.0.1:8770/train_latyshova/index.html  (API на том же адресе, без CORS-проблем).
Контракт — CLAUDE_TO_CODEX.md, запись 6. Ключи моделей остаются в pipeline/.env.* и в ответы не попадают.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core.llm import LLM, load_env  # noqa: E402
from laboratory import LabTutor, activity, candidates, evaluate, excerpt, lab_context, registry, tutor_hint
from core.tutor import Library, TutorError, chat  # noqa: E402

MAX_BODY = 5 * 1024 * 1024
UPLOAD_TYPES = {"txt", "md"}


def make_handler(lib: Library, llm: LLM, out_dir: Path):
    lab_model = LabTutor(llm)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(out_dir), **kw)

        def log_message(self, fmt, *args):
            if "/api/" in (self.path or ""):
                sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

        def end_headers(self):
            if self.path.startswith("/api/"):
                self.send_header("Access-Control-Allow-Origin", "*")  # курс, открытый как file://
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, status: int, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str):
            self._json(status, {"error": {"code": code, "message": message}})

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise TutorError(413, "too_large", "Запрос больше 5 МБ")
            try:
                return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise TutorError(400, "bad_json", "Тело запроса — не JSON") from None

        def do_OPTIONS(self):
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.startswith("/api/lab/media/"):
                asset = next((a for a in registry() if path == "/api/lab/media/" + a["asset_id"]), None)
                if not asset or not (HERE / asset["media_url"]).is_file():
                    return self._error(404, "missing_image", "Фотография недоступна.")
                body = (HERE / asset["media_url"]).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            if path == "/api/health":
                return self._json(200, {"ok": True, "laboratory": True, "model": llm.name, "mock": llm.is_mock,
                                        "providers": [p.name for p in llm.providers]})
            if path == "/api/sources":
                return self._json(200, {"sources": lib.list()})
            if path.startswith("/api/"):
                return self._error(404, "not_found", "Нет такого метода")
            if path in ("/", "/index.html"):
                return self._catalog()
            return super().do_GET()

        def _catalog(self):
            """Каталог курсов вместо служебного «Directory listing»."""
            import html as H
            rows = []
            for s in sorted(lib.list(), key=lambda x: x.get("folder") or ""):
                if s.get("kind") != "chapter" or not s.get("folder"):
                    continue
                layer = lib.sources[s["id"]].layer or {}
                ch = layer.get("chapter", {})
                model = (ch.get("built_with") or {}).get("model", "")
                draft = model == "mock"
                kind = "обучающая" if s["folder"].startswith("train") else "контрольная" if s["folder"].startswith("ctrl") else "глава"
                rows.append(f'<a class="c{" draft" if draft else ""}" href="{H.escape(s["folder"])}/index.html">'
                            f'<small>{kind} · {H.escape(ch.get("author", ""))} · стр. {"–".join(map(str, s.get("pages") or []))}</small>'
                            f'<b>{H.escape(ch.get("title", s["name"]))}</b><span>{H.escape(ch.get("book", ""))}</span>'
                            f'<em>{"черновик: глава ещё не обработана моделью" if draft else f"шагов {s['nodes']} · собрано моделью {H.escape(model)}"}</em></a>')
            page = ("<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                    "<title>Глава → курс</title><style>:root{color-scheme:light dark;--bg:#f6f7fa;--card:#fff;--ink:#202334;--mut:#575c70;--acc:#4338ca}"
                    "@media(prefers-color-scheme:dark){:root{--bg:#151621;--card:#1d1f2d;--ink:#f2f0fb;--mut:#b4b7cd;--acc:#b9b1ff}}"
                    "body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui}main{max-width:960px;margin:auto;padding:32px 16px}"
                    "h1{margin:0 0 4px}p{color:var(--mut)}.g{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}"
                    ".c{display:grid;gap:4px;padding:16px;border-radius:12px;background:var(--card);color:inherit;text-decoration:none;border:1px solid #8884}"
                    ".c:hover,.c:focus-visible{border-color:var(--acc)}.c small,.c span{color:var(--mut)}.c em{font-style:normal;color:var(--acc);font-size:.9em}"
                    ".draft{opacity:.7}.draft em{color:var(--mut)}</style><main><h1>Глава → курс</h1>"
                    f"<p>Курсы по главам книг. Тьютор: {H.escape(llm.name)}.</p><div class=g>{''.join(rows)}</div></main>")
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                if path in ("/api/lab/open", "/api/lab/grade", "/api/lab/hint", "/api/lab/recommend"):
                    req = self._body()
                    node = lab_context(lib, req)
                    if path.endswith("/recommend"):
                        return self._json(200, {"available": bool(candidates(excerpt(node)))})
                    operation = {"/api/lab/open": activity, "/api/lab/grade": evaluate, "/api/lab/hint": tutor_hint}[path]
                    try:
                        result = operation(lab_model, node, req)
                    except ValueError as error:
                        return self._error(400, "bad_activity", str(error))
                    if result.get("action") == "study_text":
                        c = next((c for c in node.get("claims", []) if c.get("verified") and c.get("quote")), None)
                        result["evidence"] = {"quote": c["quote"][:1200], "page": c.get("page")} if c else None
                    return self._json(200, result)
                if path == "/api/chat":
                    req = self._body()
                    reply = chat(lib, llm, req)
                    if reply["mode"] == "practice":
                        for sid in reversed(req["sources"]):
                            src = lib.get(sid)
                            if src.layer and req.get("lesson") not in src.nodes:
                                continue
                            node = lab_context(lib, {"source": sid, "node": req.get("lesson")})
                            if candidates(excerpt(node)):
                                reply["action"] = {"type": "open_virtual_lab", "source": sid, "node": req.get("lesson")}
                                break
                    return self._json(200, reply)
                if path == "/api/sources":
                    req = self._body()
                    name = str(req.get("name") or "файл.txt")
                    ext = name.rsplit(".", 1)[-1].lower()
                    if ext not in UPLOAD_TYPES:
                        raise TutorError(415, "unsupported_type",
                                         "Пока принимаются только TXT и Markdown; PDF и DOCX — в работе")
                    src = lib.add_text(name, str(req.get("text") or ""))
                    return self._json(201, src.meta())
                if path == "/api/reload":
                    lib.reload()
                    return self._json(200, {"sources": lib.list()})
                return self._error(404, "not_found", "Нет такого метода")
            except TutorError as e:
                return self._error(e.status, e.code, e.message)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._error(500, "internal", f"{type(e).__name__}: {e}")

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=int(os.getenv("TUTOR_PORT", "8770")))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--out", default=str(HERE / "out"), help="папка с собранными главами (out/<глава>/layer.json)")
    p.add_argument("--llm", help="цепочка профилей: gemini,qwen | qwen | gemini | mock")
    args = p.parse_args()
    load_env()
    out_dir = Path(args.out).resolve()
    lib = Library(out_dir)
    llm = LLM(args.llm or os.getenv("LLM_PROFILES_CHAT") or None)  # чат: по умолчанию быстрый Gemini
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(lib, llm, out_dir))
    print(f"Тьютор: http://{args.host}:{args.port}/  модель: {llm.name}  источников: {len(lib.list())}", flush=True)
    for s in lib.list():
        print(f"  {s['id']:<14} {s['folder']}/index.html  ({s['units']} абзацев, {s['nodes']} шагов)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
