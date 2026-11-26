"""Конвейер «Глава → курс». Одна команда на главу.

  py -3 run.py all --chapter train_latyshova      слой + проверка + курс
  py -3 run.py all --set train                    все обучающие главы (train | control | all)
  py -3 run.py verify --chapter train_latyshova   перепроверить out/<глава>/layer.json после ручной правки и пересобрать курс
  py -3 run.py units --chapter train_latyshova    только нарезка на единицы (out/<глава>/units.json)
  py -3 run.py check --chapter X --package pkg.json [--key key.json]   модуль проверки закладок
  py -3 run.py check --chapter X                  самопроверка на синтетических закладках из своего слоя
  py -3 run.py edit --chapter X --node ID --minutes 4 --what "исправил цитату"   запись в журнал ручных правок
  py -3 run.py journal                            человеко-минуты по главам
  py -3 run.py video --spec video/specs/shorts_caliper.json   ролик + субтитры + паспорт из спецификации сцены
  py -3 run.py export --chapter X                 официальные форматы организаторов → out/<глава>/official (+ проверка схемами)
  py -3 run.py review --package <папка>/package.json   модуль проверки по формату организаторов → out/review/<id>/answer.json
  py -3 run.py quota                              какие модели сейчас отвечают (по 1 крошечному запросу на модель)
  --llm gemini,qwen | qwen | gemini | mock        выбор моделей на один запуск (по умолчанию LLM_PROFILES из .env)

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
from core.llm import LLM, LLMError, load_env, probe, read_profile, usage_today  # noqa: E402
from core.illustrate import illustrate  # noqa: E402
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
    llm = LLM(args.llm or os.getenv("LLM_PROFILES_BUILD") or None)  # анализ книг: по умолчанию серверный Qwen
    llm.namespace = cid  # кеш ответов модели — в папке этой главы
    log(f"{cid}: {len(units)} единиц, модель {llm.name}")
    layer, coverage = build_layer(cid, cfg, units, llm, pack, log)
    if pdf:
        layer["chapter"]["pdf_first_page"] = cut_pdf(pdf, [u["page"] for u in units], out / "source.pdf")
    n_ill = illustrate(layer, out)
    report = verify_layer(layer, units, coverage)
    report["illustrations"] = n_ill
    report.update(status="ok", chapter=cid, model=llm.name, llm_calls=llm.calls, cache_hits=llm.cache_hits,
                  seconds=round(time.monotonic() - t0, 1))
    save_json(out / "layer.json", layer)
    save_json(out / "coverage.json", coverage)
    from core.export import export_chapter
    report["official"] = {k: v["ok"] for k, v in export_chapter(cid, cfg, layer, units, coverage, out).items()}
    save_json(out / "report.json", report)
    render(layer, out, log)
    log(f"{cid}: официальные форматы {report['official']}")
    r = report["requirements"]
    log(f"{cid}: узлов {report['nodes']}, заданий {report['tasks']} {report['task_types']}, "
        f"цитаты проверены {report['claims_verified_share']:.0%}, покрытие {report['coverage']}, требования {r}")
    return report


def reverify(cid: str, args, log) -> dict:
    out = Path(args.out) / cid
    layer = json.loads((out / "layer.json").read_text(encoding="utf-8"))
    units = json.loads((out / "units.json").read_text(encoding="utf-8"))
    coverage = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    old = out / "report.json"
    report = json.loads(old.read_text(encoding="utf-8")) if old.is_file() else {}  # модель, запросы, схемы — из сборки
    report.update(verify_layer(layer, units, coverage))
    report.update(status="ok", chapter=cid, stage="verify")
    save_json(out / "layer.json", layer)
    save_json(out / "report.json", report)
    render(layer, out, log)
    log(f"{cid}: проверено, замечаний {len(report['issues'])}")
    return report


def check(cid: str, cfg: dict, args, log) -> dict:
    """Модуль проверки закладок. --package внешний пакет; без него — самопроверка на синтетических закладках."""
    from core.checker import check_package, make_synthetic, score
    out = Path(args.out) / cid
    units = json.loads((out / "units.json").read_text(encoding="utf-8"))
    pack = json.loads((HERE / "domain" / cfg["domain"] / "pack.json").read_text(encoding="utf-8"))
    system = (HERE / "prompts" / "checker.txt").read_text(encoding="utf-8").format()
    if args.package:
        pkg, key = json.loads(Path(args.package).read_text(encoding="utf-8")), None
        if args.key:
            key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    else:
        layer = json.loads((out / "layer.json").read_text(encoding="utf-8"))
        pkg, key = make_synthetic(layer)
        save_json(out / "synthetic_package.json", pkg)
        save_json(out / "synthetic_key.json", key)
    res = check_package(pkg, units, LLM(args.llm), pack, system, log)
    if key:
        res["score"] = score(res["remarks"], key)
        log(f"{cid}: самопроверка {res['score']}")
    save_json(out / "remarks.json", res)
    log(f"{cid}: замечаний {len(res['remarks'])} → {out / 'remarks.json'}")
    return res


def main():
    # --env <файл> — профиль модели (например .env.qwen); читается раньше .env и имеет приоритет.
    if "--env" in sys.argv:
        i = sys.argv.index("--env")
        load_env(HERE / sys.argv[i + 1])
        del sys.argv[i:i + 2]
    load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["all", "verify", "units", "check", "edit", "journal", "quota", "video", "export", "review"])
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--chapter")
    g.add_argument("--set", choices=["train", "control", "test", "all"])
    p.add_argument("--books-md")
    p.add_argument("--books-pdf")
    p.add_argument("--out", default=str(HERE / "out"))
    p.add_argument("--config", default=str(HERE / "chapters.json"))
    p.add_argument("--llm", help="цепочка профилей моделей, например gemini,qwen или qwen или mock (файлы .env.<имя>)")
    p.add_argument("--spec", help="video: спецификация сцены (video/specs/*.json)")
    p.add_argument("--package", help="check: внешний пакет с закладками (JSON)")
    p.add_argument("--key", help="check: ключ для самопроверки")
    p.add_argument("--minutes", type=float, help="edit: сколько минут заняла ручная правка")
    p.add_argument("--what", help="edit: что исправлено")
    p.add_argument("--node", default="", help="edit: id узла")
    p.add_argument("--who", default="")
    p.add_argument("--file", default="", help="edit: какой файл изменён")
    p.add_argument("--people", type=int, default=1, help="edit: сколько человек правило")
    p.add_argument("--run-no", type=int, default=1, help="edit: номер прогона, результат которого правили")
    p.add_argument("--reason", default="", help="edit: почему понадобилась правка")
    args = p.parse_args()
    chapters = json.loads(Path(args.config).read_text(encoding="utf-8"))["chapters"]
    from core import journal
    if args.cmd == "video":
        from video.build import build as build_video
        if not args.spec:
            p.error("video: нужен --spec")
        build_video(Path(args.spec), Path(args.out) / "video", print)
        return
    if args.cmd == "review":
        from core.review import review_package
        if not args.package:
            p.error("review: нужен --package <review_package.json>")
        pkg_path = Path(args.package)
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        md = pkg_path.parent / pkg["chapter_file"]
        physics_path = HERE / "domain" / "geology" / "official" / "physics_checklist.json"
        physics = json.loads(physics_path.read_text(encoding="utf-8")) if physics_path.is_file() else None
        rllm = LLM(args.llm or os.getenv("LLM_PROFILES_REVIEW") or os.getenv("LLM_PROFILES_CHAT") or None)
        rllm.namespace = "review_" + pkg.get("package_id", "package")
        res = review_package(pkg, md, rllm, physics, print)
        dest = Path(args.out) / "review" / pkg.get("package_id", "package")
        save_json(dest / "answer.json", res["answer"])
        save_json(dest / "rejected.json", res["rejected"])
        print(f"замечаний {len(res['answer']['remarks'])} из {res['targets']} целей, отклонено без доказательства {len(res['rejected'])}, модель {res['model']} → {dest / 'answer.json'}")
        return
    if args.cmd == "quota":
        print("Запросов за 24 часа:", json.dumps(usage_today(), ensure_ascii=False))
        for name in (args.llm or os.getenv("LLM_PROFILES", "gemini")).split(","):
            name = name.strip()
            extra = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                     "gemini-flash-lite-latest"] if "googleapis" in read_profile(name).get("LLM_BASE_URL", "") else None
            for r in probe(name, extra):
                print(f"  {r['profile']:7} {r['model'][-42:]:42} {r['status']:22} {r.get('limit', ''):12} {r['seconds']} с")
        print("Остаток Google не сообщает: лимит виден только когда исчерпан. Сброс суточных квот — полночь по Тихоокеанскому времени (≈13:00 по Алматы).")
        return
    if args.cmd == "journal":
        print(json.dumps(journal.summary(), ensure_ascii=False, indent=1))
        return
    if not (args.chapter or args.set):
        p.error("нужен --chapter или --set")
    if args.cmd == "edit":
        if not (args.chapter and args.minutes is not None and args.what):
            p.error("edit: нужны --chapter, --minutes, --what")
        print(journal.add(args.chapter, args.minutes, args.what, args.node, args.who, file=args.file,
                          people=args.people, run_no=args.run_no, reason=args.reason))
        return
    ids = [args.chapter] if args.chapter else [k for k, c in chapters.items() if args.set in ("all", c["set"])]
    log = lambda m: print(m, flush=True)
    failed = 0
    for cid in ids:
        if cid not in chapters:
            raise SystemExit(f"Нет главы {cid} в {args.config}")
        try:
            if args.cmd == "verify":
                reverify(cid, args, log)
            elif args.cmd == "export":
                from core.export import export_chapter
                o = Path(args.out) / cid
                rd = lambda f: json.loads((o / f).read_text(encoding="utf-8"))
                res = export_chapter(cid, chapters[cid], rd("layer.json"), rd("units.json"), rd("coverage.json"), o)
                log(f"{cid}: {o / 'official'} " + json.dumps({k: (v['ok'] or v['errors'][:2]) for k, v in res.items()}, ensure_ascii=False))
            elif args.cmd == "check":
                check(cid, chapters[cid], args, log)
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
