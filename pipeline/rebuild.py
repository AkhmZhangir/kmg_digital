"""Проверка сохранённого учебного слоя по исходной книге и пересборка HTML."""
import argparse
import json
from pathlib import Path

from build import render, units_for, validate
from extract import extract


def rebuild(book, layer_path):
    layer=json.loads(layer_path.read_text())
    nodes=layer["nodes"]
    if len({n["id"] for n in nodes})!=len(nodes):
        raise ValueError("Повтор идентификатора узла")
    if not nodes: raise ValueError("Пустой учебный слой")
    pages={p["pdf_page"]:p for p in extract(book,min(n["page"] for n in nodes),max(n["page"] for n in nodes))}
    for n in nodes:
        source=[u for u in units_for(pages[n["page"]],book.stem) if u["kind"]!="описание иллюстрации OCR"]
        validate(n,source)
    render(layer,layer_path.parent)
    print("Проверено узлов:",len(nodes))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book",type=Path)
    parser.add_argument("layer",type=Path)
    args=parser.parse_args()
    rebuild(args.book,args.layer)
