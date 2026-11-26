"""Журнал ручных правок: каждая правка человека с минутами. Человеко-минуты на узел = стоимость масштабирования.
Журнал лежит в git (journal/edits.jsonl) и должен совпадать с историей коммитов: в записи хранится commit."""
import csv
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
JOURNAL = HERE.parent / "journal" / "edits.jsonl"
CSV = HERE.parent / "journal" / "manual_edits.csv"  # формат организаторов (05_шаблоны/manual_edits.csv)
CSV_FIELDS = ["time", "chapter", "file", "what_changed", "person_minutes", "people", "run_no", "reason"]


def add(chapter: str, minutes: float, what: str, node: str = "", who: str = "", kind: str = "fix",
        file: str = "", people: int = 1, run_no: int = 1, reason: str = "") -> dict:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "chapter": chapter, "node": node, "minutes": float(minutes),
           "kind": kind, "what": what, "who": who, "commit_before": sha}
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    new = not CSV.is_file()
    with CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(CSV_FIELDS)
        w.writerow([row["at"][:16], chapter, file or f"pipeline/out/{chapter}/layer.json" + (f"#{node}" if node else ""),
                    what, float(minutes), int(people), int(run_no), reason or kind])
    return row


def summary() -> dict:
    if not JOURNAL.is_file():
        return {}
    out = {}
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            s = out.setdefault(r["chapter"], {"edits": 0, "minutes": 0.0, "nodes": set()})
            s["edits"] += 1
            s["minutes"] += r["minutes"]
            if r.get("node"):
                s["nodes"].add(r["node"])
    return {k: {"edits": v["edits"], "minutes": round(v["minutes"], 1), "nodes_touched": len(v["nodes"])} for k, v in out.items()}
