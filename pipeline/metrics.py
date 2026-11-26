"""metrics.csv по шаблону организаторов: одна строка на главу и этап (layer, routing, course, video, review).

  py -3 metrics.py            → ../deliverables/metrics.csv

Источники: out/<глава>/report.json и layer.json, кеш ответов модели .cache/llm/<глава>/ (число запросов и
выходные токены ≈ символы/4 — точный счёт токенов бесплатные API отдают не всегда), журнал ручных правок
journal/edits.jsonl, паспорт ролика. Деньги 0: все модели — бесплатные квоты или свой сервер.
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIELDS = ["chapter", "stage", "nodes", "llm_tokens_in", "llm_tokens_out", "money_usd", "person_minutes",
          "mentor_minutes", "video_seconds", "manual_share"]
STAGE_TASKS = {"layer": {"outline", "node", "fix_quotes", "fix-quotes", "fix"}, "course": {"tasks"}, "review": {"review"}}


def cache_stats(folder: Path) -> dict:
    out = {}
    for f in folder.glob("*.json") if folder.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stage = next((s for s, ts in STAGE_TASKS.items() if d.get("task") in ts), "layer")
        s = out.setdefault(stage, [0, 0])
        s[0] += 1
        s[1] += len(str(d.get("raw") or "")) // 4
    return out


def journal_minutes() -> dict:
    j = ROOT / "journal" / "edits.jsonl"
    out = {}
    for line in j.read_text(encoding="utf-8").splitlines() if j.is_file() else []:
        if line.strip():
            r = json.loads(line)
            out[r["chapter"]] = out.get(r["chapter"], 0) + float(r["minutes"])
    return out


def main() -> None:
    rows, mins = [], journal_minutes()
    sys.path.insert(0, str(HERE))
    from core import journal
    touched = {k: v["nodes_touched"] for k, v in journal.summary().items()}  # доля узлов, которые правил человек
    passport = ROOT / "deliverables" / "video" / "passport.json"
    video = json.loads(passport.read_text(encoding="utf-8")) if passport.is_file() else {}
    for course in sorted(HERE.glob("out/*/report.json")):
        cid = course.parent.name
        if not (cid.startswith("train_") or cid.startswith("ctrl_") or cid.startswith("test_")):
            continue
        rep = json.loads(course.read_text(encoding="utf-8"))
        cache = cache_stats(HERE / ".cache" / "llm" / cid)
        m = mins.get(cid, 0.0)
        vsec = 0.0
        if video.get("chapter") == cid:
            vsec = round(max((float(s.get("end") or 0) for s in video.get("scenes") or []), default=0), 1)
        for stage in ("layer", "routing", "course", "video", "review"):
            calls, tok = cache.get(stage, [0, 0])
            rows.append({"chapter": cid, "stage": stage, "nodes": rep.get("nodes", ""), "llm_tokens_in": "",
                         "llm_tokens_out": tok or 0, "money_usd": 0, "person_minutes": m if stage == "layer" else 0,
                         "mentor_minutes": 0, "video_seconds": vsec if stage == "video" else 0,
                         "manual_share": round(touched.get(cid, 0) / rep["nodes"], 3) if stage == "layer" and rep.get("nodes") else 0})
    dest = ROOT / "deliverables" / "metrics.csv"
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{dest}: {len(rows)} строк")


if __name__ == "__main__":
    main()
