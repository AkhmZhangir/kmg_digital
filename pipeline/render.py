"""Render a contract v1 chapter for offline use. Core provides media in out_dir."""
import argparse
import json
import shutil
from pathlib import Path

WEB = Path(__file__).with_name("web")


def render(layer: dict, out_dir: Path) -> None:
    if layer.get("schema_version") != "1.0" or not layer.get("nodes"):
        raise ValueError("Ожидается учебный слой версии 1.0 с узлами")
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(WEB, out_dir / "web", dirs_exist_ok=True, ignore=shutil.ignore_patterns("index.html"))
    template = (WEB / "index.html").read_text(encoding="utf-8")
    data = json.dumps(layer, ensure_ascii=False).replace("<", "\\u003c")
    (out_dir / "index.html").write_text(template.replace("__LAYER__", data), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layer", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    layer = json.loads(args.layer.read_text(encoding="utf-8"))
    render(layer, args.out)
    assets = args.layer.parent / "media"
    if assets.is_dir() and assets.resolve() != (args.out / "media").resolve():
        shutil.copytree(assets, args.out / "media", dirs_exist_ok=True)
    pdf = layer["chapter"].get("pdf")
    if pdf and Path(pdf).name == pdf:
        src = args.layer.parent / pdf
        if src.is_file() and src.resolve() != (args.out / pdf).resolve():
            shutil.copy2(src, args.out / pdf)
