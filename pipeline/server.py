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
from core.tutor import Library, TutorError, chat  # noqa: E402

MAX_BODY = 5 * 1024 * 1024
UPLOAD_TYPES = {"txt", "md"}


def make_handler(lib: Library, llm: LLM, out_dir: Path):
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
            if path == "/api/health":
                return self._json(200, {"ok": True, "model": llm.name, "mock": llm.is_mock,
                                        "providers": [p.name for p in llm.providers]})
            if path == "/api/sources":
                return self._json(200, {"sources": lib.list()})
            if path.startswith("/api/"):
                return self._error(404, "not_found", "Нет такого метода")
            return super().do_GET()

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                if path == "/api/chat":
                    return self._json(200, chat(lib, llm, self._body()))
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
    llm = LLM(args.llm)
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
