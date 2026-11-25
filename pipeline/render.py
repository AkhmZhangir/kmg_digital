"""Render a contract v1 chapter for offline use. Core provides media in out_dir."""
import argparse
import json
import shutil
from pathlib import Path

WEB = Path(__file__).with_name("web")


def _artifact(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def course_page(layer: dict, artifacts: Path | None = None, *, assets="web/") -> str:
    template = (WEB / "index.html").read_text(encoding="utf-8").replace('"web/', '"' + assets)
    if artifacts is not None:
        layer = {**layer, "course_audit": {
            "report": _artifact(artifacts / "report.json"),
            "coverage": _artifact(artifacts / "coverage.json"),
            "validation": _artifact(artifacts / "official" / "validation.json"),
        }}
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
