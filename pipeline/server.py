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
import re
import sys
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core.llm import LLM, load_env  # noqa: E402
from laboratory import LabTutor, activity, candidates, evaluate, excerpt, lab_context, registry, tutor_hint, catalogue, observation_hint
from core.tutor import Library, TutorError, chat  # noqa: E402

from spaces import MAX_FILE, Spaces
from assessments import generate, search_sources

MAX_BODY = 5 * 1024 * 1024
UPLOAD_TYPES = {"txt", "md"}


def make_handler(lib: Library, llm: LLM, out_dir: Path):
    out_dir = out_dir.resolve()
    lab_model = LabTutor(llm)
    spaces = Spaces(out_dir / ".geocourse" / "spaces.sqlite3")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(out_dir), **kw)

        def log_message(self, fmt, *args):
            if "/api/" in (self.path or ""):
                sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

        def end_headers(self):
            if self.path.startswith("/api/") and not self.path.startswith("/api/spaces"):
                self.send_header("Access-Control-Allow-Origin", "*")  # курс, открытый как file://
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            if self.path.startswith("/api/"):
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

        def _length(self):
            try:
                return int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise TutorError(400, "bad_length", "Некорректный размер запроса.") from None

        def _body(self):
            n = self._length()
            if not 0 <= n <= MAX_BODY:
                raise TutorError(413, "too_large", "Запрос больше 5 МБ")
            try:
                value = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if not isinstance(value, dict):
                    raise TutorError(400, "bad_json", "Ожидается JSON-объект.")
                return value
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise TutorError(400, "bad_json", "Тело запроса — не JSON") from None

        def do_OPTIONS(self):
            self.send_response(204)
            self.end_headers()

        def _send(self, body, kind, disposition=None):
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if disposition:
                self.send_header("Content-Disposition", disposition)
            self.end_headers()
            self.wfile.write(body)

        def translate_path(self, path):
            # Keep private workspace storage outside the public static namespace.
            public = Path(super().translate_path(path))
            relative = public.relative_to(out_dir)
            if relative.parts and relative.parts[0] in {"assets", ".geocourse"}:
                if relative.parts[0] == "assets":
                    return str(HERE / "web" / Path(*relative.parts[1:]))
                return str(out_dir / ".private-unavailable")
            return str(public)

        def do_GET(self):
            try:
                self._check_space_origin()
                return self._get()
            except TutorError as e:
                return self._error(e.status, e.code, e.message)

        def _check_space_origin(self):
            if not self.path.startswith("/api/spaces"):
                return
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                raise TutorError(403, "wrong_origin", "Откройте учебное пространство на странице QABAT.")

        def _lesson_page(self, layer):
            data = json.dumps(layer, ensure_ascii=False).replace("<", "\\u003c")
            template = (HERE / "web" / "index.html").read_text(encoding="utf-8").replace('"web/', '"/assets/')
            return self._send(template.replace("__LAYER__", data).encode(), "text/html; charset=utf-8")

        def _get(self):
            path = self.path.split("?")[0]
            if path == "/api/spaces":
                return self._json(200, {"spaces": spaces.list()})
            if path == "/api/search":
                query = parse_qs(urlsplit(self.path).query).get("q", [""])[0].strip()
                return self._json(200, {"hits": search_sources(lib, query) if 0 < len(query) <= 120 else []})
            if path.startswith("/api/build/"):
                from core.webbuild import status as build_status
                st = build_status(path.rsplit("/", 1)[-1])
                return self._json(200, st) if st else self._error(404, "not_found", "Нет такой сборки")
            if path == "/api/catalog":
                courses = {item["folder"]: item for item in lib.list() if item["kind"] == "chapter"}
                return self._json(200, {"courses": [
                    {**item, "chapter": lib.get(item["id"]).layer["chapter"]} for item in courses.values()
                ]})
            space_page = re.fullmatch(r"/spaces/([a-f0-9]{32})/?", path)
            if space_page:
                space = spaces.view(space_page[1])
                chapter = {"id": "space-" + space["id"], "title": space["name"], "pages": []}
                return self._lesson_page({"space_id": space["id"], "chapter": chapter, "nodes": [], "parts": []})
            match = re.fullmatch(r"/api/spaces/([a-f0-9]{32})(?:/files/(src-[a-f0-9]{32})(/text)?)?", path)
            if match:
                sid, eid, preview = match.groups()
                if not eid:
                    return self._json(200, spaces.view(sid))
                if preview:
                    src = spaces.get_source(sid, eid)
                    return self._json(200, {"text": "\n\n".join(u["text"] for u in src.units[:25])})
                row = spaces.original(sid, eid)
                kind = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}.get(row["ext"], "text/plain; charset=utf-8")
                mode = "inline" if row["ext"] == ".pdf" else "attachment"
                filename = row["name"]
                if not filename.lower().endswith(row["ext"]):
                    filename += row["ext"]
                return self._send(row["original"], kind, mode + "; filename*=UTF-8''" + quote(filename, safe=""))
            if path == "/api/lab/catalogue":
                return self._json(200, {"assets": catalogue()})
            media = re.fullmatch(r"/api/lab/media/([a-z0-9_]+)(?:/(ppl|xpl))?", path)
            if media:
                asset = next((a for a in registry() if media[1] == a["asset_id"]), None)
                item = asset.get("views", {}).get(media[2]) if asset and media[2] else asset and asset["media_url"]
                if not item or not (HERE / item).is_file():
                    return self._error(404, "missing_image", "Фотография недоступна.")
                return self._send((HERE / item).read_bytes(), "image/jpeg")
            if path == "/api/health":
                return self._json(200, {"ok": True, "laboratory": True, "model": llm.name, "mock": llm.is_mock,
                                        "providers": [p.name for p in llm.providers]})
            if path == "/api/sources":
                return self._json(200, {"sources": lib.list()})
            if path.startswith("/api/"):
                return self._error(404, "not_found", "Нет такого метода")
            if path in ("/", "/index.html"):
                return self._catalog()
            course = re.fullmatch(r"/([^/]+)(?:/index\.html|/)", path)
            if course:
                folder = Path(super().translate_path("/" + course[1]))
                for src in lib.sources.copy().values():
                    if src.folder == folder and src.layer.get("schema_version") == "1.0" and src.nodes:
                        return self._lesson_page(src.layer)
            return super().do_GET()

        def _catalog(self):
            return self._send((HERE / "web" / "home.html").read_bytes(), "text/html; charset=utf-8")

        def do_POST(self):
            url = urlsplit(self.path)
            path = url.path
            try:
                self._check_space_origin()
                if path == "/api/spaces":
                    return self._json(201, spaces.create(self._body().get("name")))
                scope = re.fullmatch(r"/api/spaces/([a-f0-9]{32})(?:/(upload|build|chat|assessments|lab/(?:open|grade|hint|recommend|observation)))?", path)
                active_lib = lib
                if scope:
                    space_id, operation = scope.groups()
                    if not operation:
                        return self._json(200, spaces.edit(space_id, self._body()))
                    if operation == "build":
                        from core.webbuild import start as build_start
                        return self._json(202, build_start(spaces, space_id, str(self._body().get("entry") or ""), lib, out_dir))
                    if operation == "upload":
                        size = self._length()
                        if not 0 < size <= MAX_FILE:
                            raise TutorError(413, "file_size", "Выберите файл размером до 32 МБ.")
                        if self.headers.get_content_type() != "application/octet-stream":
                            raise TutorError(415, "bad_upload", "Ожидается содержимое файла.")
                        params = parse_qs(url.query)
                        raw = self.rfile.read(size)
                        if len(raw) != size:
                            raise TutorError(400, "incomplete_upload", "Загрузка прервалась. Повторите попытку.")
                        result = spaces.upload(space_id, params.get("name", [""])[0], params.get("parent", [None])[0], raw)
                        return self._json(201, result)
                    active_lib = SimpleNamespace(get=lambda eid: spaces.get_source(space_id, eid))
                    path = "/api/" + operation
                if path == "/api/lab/observation":
                    try:
                        return self._json(200, observation_hint(lab_model, self._body()))
                    except ValueError as error:
                        return self._error(400, "bad_observation", str(error))
                if path in ("/api/lab/open", "/api/lab/grade", "/api/lab/hint", "/api/lab/recommend"):
                    req = self._body()
                    node = lab_context(active_lib, req)
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
                if path == "/api/assessments":
                    return self._json(200, generate(active_lib, llm, self._body()))
                if path == "/api/chat":
                    req = self._body()
                    reply = chat(active_lib, llm, req)
                    if reply["mode"] == "practice":
                        for sid in reversed(req["sources"]):
                            src = active_lib.get(sid)
                            if src.layer and req.get("lesson") not in src.nodes:
                                continue
                            node = lab_context(active_lib, {"source": sid, "node": req.get("lesson")})
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
                return self._error(500, "internal", "Внутренняя ошибка сервера.")

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
