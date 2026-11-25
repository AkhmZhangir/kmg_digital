"""Local workspaces. Course builds remain in the existing catalog."""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile
from subprocess import SubprocessError

from core.tutor import Source, TutorError, _chunks
from prepare import FORMATS, read_pdf, read_docx

MAX_FILE = 32 * 1024 * 1024


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def name_value(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 150 or "\x00" in value:
        raise TutorError(400, "bad_name", "Укажите название длиной до 150 символов.")
    return value.strip()


def extract_units(sid, ext, raw):
    try:
        if ext in (".md", ".txt"):
            parts = re.split(r"<!--\s*page\s+(\d+)\s*-->", raw.decode("utf-8-sig"))
            pages = [(1, parts[0]), *((int(n), body) for n, body in zip(parts[1::2], parts[2::2]))]
        else:
            with TemporaryDirectory() as folder:
                path = Path(folder) / ("source" + ext)
                path.write_bytes(raw)
                pages = list(read_pdf(path, None).items()) if ext == ".pdf" else [(1, read_docx(path))]
    except UnicodeDecodeError:
        raise TutorError(400, "encoding", "Сохраните текстовый файл в UTF-8.") from None
    except (ValueError, BadZipFile, KeyError, ParseError, SubprocessError) as error:
        raise TutorError(400, "extract_failed", str(error)) from None
    except Exception as error:
        if type(error).__module__.startswith("pypdf."):
            raise TutorError(400, "invalid_pdf", "PDF повреждён или защищён паролем.") from None
        raise
    units = []
    for page, body in pages:
        for chunk in _chunks(body):
            units.append({"id": f"{sid}.u{len(units) + 1:03d}", "page": page, "text": chunk})
    if not units:
        raise TutorError(400, "empty_source", "В файле не найден читаемый текст.")
    return units


class Spaces:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db(write=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS spaces (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY, space TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
                    parent TEXT REFERENCES entries(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, kind TEXT NOT NULL, ext TEXT,
                    created TEXT NOT NULL, updated TEXT NOT NULL,
                    units TEXT, unit_count INTEGER, original BLOB
                );
                CREATE INDEX IF NOT EXISTS space_entries ON entries(space, parent);
            """)

    @contextmanager
    def db(self, write=False):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def require(self, db, sid):
        row = db.execute("SELECT * FROM spaces WHERE id = ?", (sid,)).fetchone()
        if not row:
            raise TutorError(404, "space_not_found", "Учебное пространство не найдено.")
        return row

    def entry(self, db, sid, eid):
        row = db.execute("SELECT id, parent, kind, name, ext FROM entries WHERE space = ? AND id = ?", (sid, eid)).fetchone()
        if not row:
            raise TutorError(404, "entry_not_found", "Элемент не найден в этом пространстве.")
        return row

    def list(self):
        with self.db() as db:
            return [dict(row) for row in db.execute("""
                SELECT s.*, (SELECT COUNT(*) FROM entries e WHERE e.space=s.id AND e.kind='source') AS sources
                FROM spaces s ORDER BY updated DESC, id
            """)]

    def view(self, sid):
        with self.db() as db:
            space = dict(self.require(db, sid))
            space["entries"] = [dict(row) for row in db.execute("""
                SELECT id, parent, name, kind, ext, unit_count, created, updated,
                    CASE WHEN kind = 'source' THEN 'ready' END AS status
                FROM entries WHERE space = ? ORDER BY created, rowid
            """, (sid,))]
            return space

    def create(self, name):
        sid = uuid4().hex
        now = timestamp()
        with self.db(write=True) as db:
            db.execute("INSERT INTO spaces VALUES (?, ?, ?, ?)", (sid, name_value(name), now, now))
        return self.view(sid)

    def folder(self, db, sid, parent, entry=None):
        if parent is not None and not isinstance(parent, str):
            raise TutorError(400, "bad_parent", "Выберите папку.")
        ancestor = parent
        while ancestor is not None:
            row = self.entry(db, sid, ancestor)
            if row["kind"] != "folder" or row["id"] == entry:
                raise TutorError(400, "bad_parent", "Папку нельзя переместить в себя или в её дочернюю папку.")
            ancestor = row["parent"]
        return parent

    def edit(self, sid, req):
        action = req.get("action")
        now = timestamp()
        with self.db(write=True) as db:
            self.require(db, sid)
            if action == "delete_space":
                db.execute("DELETE FROM spaces WHERE id = ?", (sid,))
                return {"deleted": True}
            if action == "rename_space":
                db.execute("UPDATE spaces SET name = ? WHERE id = ?", (name_value(req.get("name")), sid))
            elif action == "folder":
                parent = self.folder(db, sid, req.get("parent"))
                db.execute("""
                    INSERT INTO entries (id, space, parent, name, kind, created, updated)
                    VALUES (?, ?, ?, ?, 'folder', ?, ?)
                """, (uuid4().hex, sid, parent, name_value(req.get("name")), now, now))
            elif action in ("rename", "move", "delete"):
                eid = req.get("id")
                if not isinstance(eid, str):
                    raise TutorError(400, "bad_entry", "Выберите элемент.")
                row = self.entry(db, sid, eid)
                if action == "rename":
                    db.execute("UPDATE entries SET name=?, updated=? WHERE id=?", (name_value(req.get("name")), now, eid))
                elif action == "move":
                    parent = self.folder(db, sid, req.get("parent"), eid)
                    db.execute("UPDATE entries SET parent=?, updated=? WHERE id=?", (parent, now, eid))
                else:
                    if row["kind"] == "folder" and req.get("contents") not in ("keep", "delete"):
                        raise TutorError(400, "choose_contents", "Укажите, что делать с содержимым папки.")
                    if row["kind"] == "folder" and req["contents"] == "keep":
                        db.execute("UPDATE entries SET parent=NULL, updated=? WHERE parent=?", (now, eid))
                    db.execute("DELETE FROM entries WHERE id=?", (eid,))
            else:
                raise TutorError(400, "bad_action", "Действие не поддерживается.")
            db.execute("UPDATE spaces SET updated=? WHERE id=?", (now, sid))
        return self.view(sid)

    def upload(self, sid, name, parent, raw):
        name = name_value(name)
        ext = Path(name).suffix.lower()
        if ext not in FORMATS:
            raise TutorError(415, "unsupported_type", "Поддерживаются PDF, DOCX, TXT и Markdown.")
        with self.db() as db:
            self.require(db, sid)
            self.folder(db, sid, parent)
        eid = "src-" + uuid4().hex
        units = extract_units(eid, ext, raw)
        now = timestamp()
        with self.db(write=True) as db:
            self.require(db, sid)
            self.folder(db, sid, parent)
            db.execute("""
                INSERT INTO entries (id, space, parent, name, kind, ext, created, updated, units, unit_count, original)
                VALUES (?, ?, ?, ?, 'source', ?, ?, ?, ?, ?, ?)
            """, (eid, sid, parent, name, ext, now, now, json.dumps(units, ensure_ascii=False), len(units), raw))
            db.execute("UPDATE spaces SET updated=? WHERE id=?", (now, sid))
        result = self.view(sid)
        result["added"] = eid
        return result

    def get_source(self, sid, eid):
        if not isinstance(eid, str):
            raise TutorError(400, "bad_source", "Выберите источник.")
        with self.db() as db:
            row = self.entry(db, sid, eid)
        if row["kind"] != "source":
            raise TutorError(404, "source_not_found", "Источник не найден.")
        return self.index(eid, row["name"])

    @lru_cache(maxsize=16)
    def index(self, eid, name):
        with self.db() as db:
            row = db.execute("SELECT units FROM entries WHERE id=?", (eid,)).fetchone()
        if not row:
            raise TutorError(404, "source_not_found", "Источник уже удалён.")
        return Source(eid, name, json.loads(row["units"]))

    def original(self, sid, eid):
        with self.db() as db:
            row = db.execute("SELECT name, ext, original FROM entries WHERE space=? AND id=? AND kind='source'", (sid, eid)).fetchone()
        if not row:
            raise TutorError(404, "source_not_found", "Источник не найден.")
        return row
