"""Журнал ручных правок: каждая правка человека с минутами. Человеко-минуты на узел = стоимость масштабирования.
Журнал лежит в git (journal/edits.jsonl) и должен совпадать с историей коммитов: в записи хранится commit."""
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
JOURNAL = HERE.parent / "journal" / "edits.jsonl"


def add(chapter: str, minutes: float, what: str, node: str = "", who: str = "", kind: str = "fix") -> dict:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "chapter": chapter, "node": node, "minutes": float(minutes),
           "kind": kind, "what": what, "who": who, "commit_before": sha}
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
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
