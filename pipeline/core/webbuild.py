"""Сборка курса из файла, загруженного на сайт: тот же конвейер, что run.py, но в фоне на сервере.

POST /api/spaces/<space>/build {"entry": "src-…"}  → {"job": "…"}
GET  /api/build/<job>                               → {"state": queued|running|ready|error, "stage", "log": [...], "course": "<папка>/index.html"}
Готовый курс появляется в каталоге (out/up_<id>/) после lib.reload().
"""
import json
import re
import threading
import time
import traceback
import uuid
from pathlib import Path

from .export import export_chapter
from .illustrate import illustrate
from .layer import build_layer, save_json
from .llm import LLM
from .units import load_chapter
from .verify import verify_layer

HERE = Path(__file__).resolve().parent.parent
MAX_PAGES = 60
MAX_CHARS = 250_000
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_ONE_AT_A_TIME = threading.Semaphore(1)  # сборки по очереди: модель и так занята


def status(job: str) -> dict | None:
    j = JOBS.get(job)
    return None if j is None else {k: v for k, v in j.items() if k != "thread"}


def start(spaces, space_id: str, entry_id: str, lib, out_dir: Path) -> dict:
    src = spaces.get_source(space_id, entry_id)
    row = spaces.original(space_id, entry_id)
    pages = sorted({u["page"] for u in src.units})
    chars = sum(len(u["text"]) for u in src.units)
    if len(pages) > MAX_PAGES or chars > MAX_CHARS:
        from .tutor import TutorError
        raise TutorError(413, "too_big_for_course",
                         f"Для курса загрузите одну главу: до {MAX_PAGES} страниц (сейчас {len(pages)}). Тьютор при этом может отвечать по всей книге.")
    folder = "up_" + entry_id.replace("src-", "")[:10]
    with _LOCK:  # повторный запрос (вторая вкладка) — та же сборка, а не новая в очередь
        same = next((x for x in JOBS.values() if x["folder"] == folder and x["state"] in ("queued", "running")), None)
    if same:
        return status(same["job"])
    job = uuid.uuid4().hex[:12]
    JOBS[job] = {"job": job, "state": "queued", "stage": "в очереди", "log": [], "course": None, "folder": folder,
                 "name": row["name"], "pages": [pages[0], pages[-1]], "started": time.time(),
                 "progress": {"percent": 0, "done": 0, "total": None, "eta_sec": None, "elapsed_sec": 0}}
    t = threading.Thread(target=_run, args=(job, src, row, lib, out_dir / folder), daemon=True)
    JOBS[job]["thread"] = t
    t.start()
    return status(job)


def _run(job: str, src, row, lib, out: Path) -> None:
    j = JOBS[job]

    prog = {"done": 0, "chunks": 1, "nodes": 0, "outlined": 0}

    def refresh() -> None:
        # Ожидаемые запросы: разметка (куски) + заполнение шагов (~1.3 на шаг с исправлением цитат) + задания (1 на шаг).
        nodes = prog["nodes"] if prog["outlined"] >= prog["chunks"] else max(prog["nodes"], 6 * prog["chunks"])
        total = prog["chunks"] + int(nodes * 2.3) + 1
        done = min(prog["done"], total - 1)
        el = time.time() - j["started"]
        j["progress"] = {"percent": round(100 * done / total), "done": done, "total": total,
                         "eta_sec": int(el / done * (total - done)) if done else None, "elapsed_sec": int(el)}

    def log(msg: str) -> None:
        m = re.match(r"outline: кусок (\d+)/(\d+) → (\d+) узлов", str(msg))
        if m:
            prog["outlined"], prog["chunks"] = int(m.group(1)), int(m.group(2))
            prog["nodes"] += int(m.group(3))
        with _LOCK:
            j["log"] = (j["log"] + [str(msg)])[-40:]
            refresh()

    with _ONE_AT_A_TIME:
        try:
            j.update(state="running", stage="подготовка текста")
            out.mkdir(parents=True, exist_ok=True)
            by_page: dict[int, list[str]] = {}
            for u in src.units:
                by_page.setdefault(int(u["page"]), []).append(u["text"])
            md = "\n".join(f"<!-- page {p} -->\n" + "\n\n".join(t) for p, t in sorted(by_page.items()))
            (out / "book.md").write_text(md, encoding="utf-8")
            pages = sorted(by_page)
            title = Path(row["name"]).stem.replace("_", " ")
            cfg = {"set": "upload", "domain": "geology", "md": "book.md", "title": title, "book": row["name"],
                   "author": "загружено пользователем", "year": "", "types": None,
                   "segments": [{"from": pages[0], "to": pages[-1], "start": None, "end": None}]}
            if str(row["ext"]).lower() == ".pdf" and row["original"]:
                (out / "source.pdf").write_bytes(row["original"])
                cfg["_pdf"] = True
            units = [u.to_dict() for u in load_chapter(cfg, out)]
            save_json(out / "units.json", units)
            pack = json.loads((HERE / "domain" / "geology" / "pack.json").read_text(encoding="utf-8"))
            import os
            llm = LLM(os.getenv("LLM_PROFILES_BUILD") or None)
            llm.namespace = out.name
            orig = llm.chat_json

            def counted(*a, **kw):
                try:
                    return orig(*a, **kw)
                finally:
                    with _LOCK:
                        prog["done"] += 1
                        refresh()
            llm.chat_json = counted
            j["stage"] = f"анализ главы моделью ({len(units)} фрагментов)"
            layer, coverage = build_layer(out.name, cfg, units, llm, pack, log)
            if cfg.get("_pdf"):
                layer["chapter"]["pdf_first_page"] = 1
            j["stage"] = "иллюстрации и проверка"
            illustrate(layer, out)
            report = verify_layer(layer, units, coverage)
            report["official"] = {k: v["ok"] for k, v in export_chapter(out.name, cfg, layer, units, coverage, out).items()}
            report.update(status="ok", model=llm.name, llm_calls=llm.calls, cache_hits=llm.cache_hits)
            save_json(out / "layer.json", layer)
            save_json(out / "coverage.json", coverage)
            save_json(out / "report.json", report)
            j["stage"] = "сборка страниц курса"
            try:
                import render as front
                front.render(layer, out)
            except ImportError:
                from .preview import render_preview
                render_preview(layer, out)
            lib.reload()
            log(f"готово: шагов {report['nodes']}, заданий {report['tasks']}, цитаты проверены {report['claims_verified_share']:.0%}")
            j["progress"] = dict(j.get("progress") or {}, percent=100, eta_sec=0)
            j.update(state="ready", stage="готово", course=f"{out.name}/index.html",
                     summary={"nodes": report["nodes"], "tasks": report["tasks"],
                              "claims_verified_share": report["claims_verified_share"], "model": llm.name})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            j.update(state="error", stage="ошибка", error=f"{type(e).__name__}: {str(e)[:300]}")
