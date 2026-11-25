"""Render a contract v1 chapter for offline use. Core provides media in out_dir."""
import argparse
import json
import re
import shutil
from pathlib import Path

WEB = Path(__file__).with_name("web")


def _artifact(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


OFFICIAL_FILES = ("layer.json", "coverage.json", "routing.json", "tasks.json", "illustrations.json")


def read_course_audit(artifacts: Path) -> dict:
    report = _artifact(artifacts / "report.json")
    validation = _artifact(artifacts / "official" / "validation.json")
    report = report if isinstance(report, dict) else None
    validation = validation if isinstance(validation, dict) else None
    legacy = (report or {}).get("official")
    if validation is not None:
        checks = {name: result.get("ok") for name, result in validation.items() if isinstance(result, dict)}
    else:
        checks = legacy if isinstance(legacy, dict) else {}
    share = (report or {}).get("claims_verified_share")
    needs_review = (
        ((report is not None or validation is not None)
         and any(checks.get(name) is not True for name in OFFICIAL_FILES))
        or (type(share) in (int, float) and share < 0.8)
    )
    return {"report": report, "validation": validation, "needs_review": needs_review}


def reference_glossary(nodes: list) -> list:
    pack = _artifact(WEB.parent / "domain" / "geology" / "pack.json") or {}
    passages = [(node["id"], item.get("page"), text)
                for node in nodes
                for item in (*node.get("claims", []), *node.get("summary", []))
                if (text := item.get("quote") or item.get("text"))]
    entries = []
    for entry in pack.get("glossary_seed", []):
        term = entry["term"]
        # Match Russian case endings, keeping abbreviations and word boundaries exact.
        if term.endswith("ость"):
            pattern = re.escape(term[:-1]) + "(?:ь|и|ью|ей|ями|ям|ях)"
        elif term.islower() and term.endswith("р"):
            pattern = re.escape(term) + "(?:а|у|ом|е|ы|ов|ами|ам|ах)?"
        else:
            pattern = re.escape(term)
        word = re.compile(r"\b" + pattern + r"\b", re.IGNORECASE)
        for node_id, page, text in passages:
            if word.search(text):
                entries.append({**entry, "id": "ref-" + term, "node_id": node_id, "page": page,
                                "reference": True})
                break
    return entries


def course_page(layer: dict, artifacts: Path | None = None, *, assets="web/") -> str:
    template = (WEB / "index.html").read_text(encoding="utf-8").replace('"web/', '"' + assets)
    if artifacts is not None:
        layer = {**layer, "course_audit": {
            **read_course_audit(artifacts),
            "coverage": _artifact(artifacts / "coverage.json"),
        }}
    if layer.get("nodes") and not layer.get("glossary") and layer.get("chapter", {}).get("domain", "geology") == "geology":
        layer = {**layer, "glossary": reference_glossary(layer["nodes"])}
    data = json.dumps(layer, ensure_ascii=False).replace("<", "\\u003c")
    return template.replace("__LAYER__", data)


def render(layer: dict, out_dir: Path, *, artifacts: Path | None = None) -> None:
    if layer.get("schema_version") != "1.0" or not layer.get("nodes"):
        raise ValueError("Ожидается учебный слой версии 1.0 с узлами")
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(WEB, out_dir / "web", dirs_exist_ok=True, ignore=shutil.ignore_patterns("index.html"))
    (out_dir / "index.html").write_text(course_page(layer, artifacts if artifacts is not None else out_dir), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layer", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    layer = json.loads(args.layer.read_text(encoding="utf-8"))
    assets = args.layer.parent / "media"
    if assets.is_dir() and assets.resolve() != (args.out / "media").resolve():
        shutil.copytree(assets, args.out / "media", dirs_exist_ok=True)
    pdf = layer["chapter"].get("pdf")
    if pdf and Path(pdf).name == pdf:
        src = args.layer.parent / pdf
        if src.is_file() and src.resolve() != (args.out / pdf).resolve():
            shutil.copy2(src, args.out / pdf)
    render(layer, args.out, artifacts=args.layer.parent)
