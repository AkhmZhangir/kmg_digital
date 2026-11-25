"""Локальная студия подготовки курса."""
import argparse
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from build import HERE, build, save
from prepare import FORMATS, numbers

MAX_UPLOAD = 80 * 1024 * 1024
FILES = {
    "index.html": "text/html; charset=utf-8",
    "source.pdf": "application/pdf",
    "bundle.zip": "application/zip",
    "status.json": "application/json; charset=utf-8",
}
LOG = logging.getLogger(__name__)


class Studio(ThreadingHTTPServer):
    def __init__(self, port, folder, model, endpoint):
        super().__init__(("127.0.0.1", port), Handler)
        self.folder = folder
        self.model = model
        self.endpoint = endpoint
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.slots = BoundedSemaphore(3)

    def run_job(self, args):
        status = args.out / "status.json"

        def update(message, **fields):
            save(status, dict(message=message, **fields))

        try:
            update("Извлекаем текст из источника.")
            metrics = build(
                args,
                source_link="source.pdf" if args.book.suffix == ".pdf" else "",
                progress=lambda count, total: update(f"Готовим материал {count} из {total}.", done=count, total=total),
            )
            update("Упаковываем курс.")
            with ZipFile(args.out / "bundle.zip", "w", ZIP_DEFLATED) as archive:
                for name in ("index.html", "layer.json", "coverage.json", "report.json", args.book.name):
                    archive.write(args.out / name, name)
            update("Курс готов.", state="ready", metrics={name: metrics[name] for name in ("nodes", "quizzes", "linked", "units")})
        except (ValueError, BadZipFile, KeyError) as error:
            update(str(error), state="error")
        except Exception:
            LOG.exception("Сбой сборки курса")
            update("Сборка прервалась. Подробности записаны в журнал локальной студии.", state="error")
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def send_data(self, body, kind, status=HTTPStatus.OK, attachment=None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        length = body.stat().st_size if isinstance(body, Path) else len(body)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        if isinstance(body, Path):
            with body.open("rb") as stream:
                while chunk := stream.read(256 * 1024):
                    self.wfile.write(chunk)
        else:
            self.wfile.write(body)

    def respond(self, obj, status=HTTPStatus.OK):
        self.send_data(json.dumps(obj, ensure_ascii=False).encode(), FILES["status.json"], status)

    def allowed(self):
        homes = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        return host in homes and origin in (None, f"http://{host}")

    def do_GET(self):
        if not self.allowed():
            return self.send_error(HTTPStatus.FORBIDDEN)
        path = urlsplit(self.path).path
        if path == "/":
            return self.send_data(HERE / "studio.html", FILES["index.html"])
        if path == "/demo":
            return self.send_data(HERE / "demo" / "index.html", FILES["index.html"])
        if path == "/api/config":
            return self.respond({"model": self.server.model, "limitMb": MAX_UPLOAD // (1024 * 1024)})
        match = re.fullmatch(r"/courses/([a-f0-9]{32})/([a-z.]+)", path)
        if match and match[2] in FILES:
            file = self.server.folder / match[1] / match[2]
            if file.is_file():
                return self.send_data(file, FILES[match[2]], attachment="course.zip" if match[2] == "bundle.zip" else None)
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not self.allowed():
            return self.send_error(HTTPStatus.FORBIDDEN)
        url = urlsplit(self.path)
        if url.path != "/api/courses":
            return self.send_error(HTTPStatus.NOT_FOUND)
        params = parse_qs(url.query)
        options = {key: values[-1] for key, values in params.items()}
        suffix = Path(options.get("file", "")).suffix.lower()
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > MAX_UPLOAD:
                raise ValueError("Выберите файл размером от 1 байта до 80 МБ.")
            if suffix not in FORMATS:
                raise ValueError("Выберите PDF, DOCX, Markdown или TXT.")
            if self.headers.get_content_type() != "application/octet-stream":
                raise ValueError("Запрос должен содержать исходный файл.")
            ranges = options.get("pages", "").strip()
            numbers(ranges)
            draft = options.get("mode") == "draft"
            if not draft and not self.server.model:
                raise ValueError("Модель не настроена. Выберите черновик или задайте LLM_MODEL и LLM_ENDPOINT.")
        except ValueError as error:
            return self.respond({"message": str(error)}, HTTPStatus.BAD_REQUEST)
        if not self.server.slots.acquire(blocking=False):
            return self.respond({"message": "Студия занята. Дождитесь окончания текущей сборки."}, HTTPStatus.TOO_MANY_REQUESTS)

        job = uuid4().hex
        out = self.server.folder / job
        book = out / ("source" + suffix)
        submitted = False
        try:
            out.mkdir(parents=True)
            with book.open("wb") as stream:
                remaining = size
                while remaining:
                    data = self.rfile.read(min(remaining, 256 * 1024))
                    if not data:
                        raise ValueError("Загрузка оборвалась. Выберите файл ещё раз.")
                    stream.write(data)
                    remaining -= len(data)
            title = options.get("title", "").strip() or Path(options["file"]).stem
            args = SimpleNamespace(book=book, out=out, title=title[:160], ranges=ranges, pdf=None,
                                   ocr=options.get("ocr") == "1", responses=None,
                                   model=None if draft else self.server.model,
                                   endpoint=None if draft else self.server.endpoint)
            save(out / "status.json", {"message": "Сборка в очереди."})
            self.server.executor.submit(self.server.run_job, args)
            submitted = True
            self.respond({"course": f"/courses/{job}/"}, HTTPStatus.ACCEPTED)
        except ValueError as error:
            self.respond({"message": str(error)}, HTTPStatus.BAD_REQUEST)
        finally:
            if not submitted:
                self.server.slots.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=HERE / ".studio")
    cli = parser.parse_args()
    model, endpoint = os.getenv("LLM_MODEL"), os.getenv("LLM_ENDPOINT")
    if bool(model) != bool(endpoint):
        parser.error("Задайте LLM_MODEL и LLM_ENDPOINT вместе.")
    if endpoint and urlsplit(endpoint).scheme not in ("http", "https"):
        parser.error("LLM_ENDPOINT должен использовать http или https.")
    server = Studio(cli.port, cli.data, model, endpoint)
    print(f"Local: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
