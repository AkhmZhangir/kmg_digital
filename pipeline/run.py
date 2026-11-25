"""Конвейер «Глава → курс». Одна команда на главу.

  py -3 run.py all --chapter train_latyshova      слой + проверка + курс
  py -3 run.py all --set train                    все обучающие главы (train | control | all)
  py -3 run.py verify --chapter train_latyshova   перепроверить out/<глава>/layer.json после ручной правки и пересобрать курс
  py -3 run.py units --chapter train_latyshova    только нарезка на единицы (out/<глава>/units.json)

Модель задаётся в pipeline/.env (см. .env.example). Без .env работает офлайн-заглушка mock.
Ответы модели кешируются в pipeline/.cache/llm: повторный запуск не тратит запросы.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core.layer import build_layer, save_json  # noqa: E402
from core.llm import LLM, LLMError, load_env  # noqa: E402
from core.preview import render_preview  # noqa: E402
from core.units import load_chapter  # noqa: E402
from core.verify import verify_layer  # noqa: E402


def find_dir(flag: str | None, env: str, pattern: str) -> Path | None:
    if flag:
        return Path(flag)
    if os.getenv(env):
        return Path(os.environ[env])
    for root in (HERE.parent, HERE.parent.parent):
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0]
    return None


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def cut_pdf(src: Path, pages: list[int], dst: Path) -> int:
    """Вырезает страницы главы из PDF. Возвращает номер первой страницы (для пересчёта #page=)."""
    from pypdf import PdfReader, PdfWriter
    reader, writer = PdfReader(str(src)), PdfWriter()
    first, last = min(pages), max(pages)
    for i in range(first - 1, min(last, len(reader.pages))):
        writer.add_page(reader.pages[i])
    with dst.open("wb") as f:
        writer.write(f)
    return first


def render(layer: dict, out: Path, log) -> None:
    preview = render_preview(layer, out)
    try:
        import render as front  # pipeline/render.py — фронтенд (Codex)
    except ImportError:
        log(f"render.py ещё нет — собран только предпросмотр: {preview}")
        return
    front.render(layer, out)
    log(f"курс: {out / 'index.html'}")


def run_chapter(cid: str, cfg: dict, args, log) -> dict:
    t0 = time.monotonic()
    out = Path(args.out) / cid
    md_dir = find_dir(args.books_md, "BOOKS_MD", "books md*/books md")
    if not md_dir:
        raise SystemExit("Не найден каталог md-книг: укажите --books-md или BOOKS_MD")
    units = [u.to_dict() for u in load_chapter(cfg, md_dir)]
    save_json(out / "units.json", units)
    if args.cmd == "units":
        log(f"{cid}: {len(units)} единиц → {out / 'units.json'}")
        return {"status": "ok", "units": len(units)}
    pdf_dir = find_dir(args.books_pdf, "BOOKS_PDF", "книги*/книги")
    pdf = next(iter(sorted(pdf_dir.glob(cfg["pdf_glob"]))), None) if pdf_dir else None
    cfg = dict(cfg, _pdf=bool(pdf), _git=git_sha())
    pack = json.loads((HERE / "domain" / cfg["domain"] / "pack.json").read_text(encoding="utf-8"))
    llm = LLM()
    log(f"{cid}: {len(units)} единиц, модель {llm.name}")
    layer, coverage = build_layer(cid, cfg, units, llm, pack, log)
    if pdf:
        layer["chapter"]["pdf_first_page"] = cut_pdf(pdf, [u["page"] for u in units], out / "source.pdf")
    report = verify_layer(layer, units, coverage)
    report.update(status="ok", chapter=cid, model=llm.name, llm_calls=llm.calls, cache_hits=llm.cache_hits,
                  seconds=round(time.monotonic() - t0, 1))
    save_json(out / "layer.json", layer)
    save_json(out / "coverage.json", coverage)
    save_json(out / "report.json", report)
    render(layer, out, log)
    r = report["requirements"]
    log(f"{cid}: узлов {report['nodes']}, заданий {report['tasks']} {report['task_types']}, "
        f"цитаты проверены {report['claims_verified_share']:.0%}, покрытие {report['coverage']}, требования {r}")
    return report


def reverify(cid: str, args, log) -> dict:
    out = Path(args.out) / cid
    layer = json.loads((out / "layer.json").read_text(encoding="utf-8"))
    units = json.loads((out / "units.json").read_text(encoding="utf-8"))
    coverage = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    report = verify_layer(layer, units, coverage)
    report.update(status="ok", chapter=cid, stage="verify")
    save_json(out / "layer.json", layer)
    save_json(out / "report.json", report)
    render(layer, out, log)
    log(f"{cid}: проверено, замечаний {len(report['issues'])}")
    return report


def main():
    load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["all", "verify", "units"])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--chapter")
    g.add_argument("--set", choices=["train", "control", "test", "all"])
    p.add_argument("--books-md")
    p.add_argument("--books-pdf")
    p.add_argument("--out", default=str(HERE / "out"))
    p.add_argument("--config", default=str(HERE / "chapters.json"))
    args = p.parse_args()
    chapters = json.loads(Path(args.config).read_text(encoding="utf-8"))["chapters"]
    ids = [args.chapter] if args.chapter else [k for k, c in chapters.items() if args.set in ("all", c["set"])]
    log = lambda m: print(m, flush=True)
    failed = 0
    for cid in ids:
        if cid not in chapters:
            raise SystemExit(f"Нет главы {cid} в {args.config}")
        try:
            if args.cmd == "verify":
                reverify(cid, args, log)
            else:
                run_chapter(cid, chapters[cid], args, log)
        except (LLMError, ValueError, KeyError) as e:
            failed += 1
            save_json(Path(args.out) / cid / "report.json",
                      {"status": "error", "chapter": cid, "stage": args.cmd, "errors": [{"message": f"{type(e).__name__}: {e}"}]})
            log(f"{cid}: ОШИБКА {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
