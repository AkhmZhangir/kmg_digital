"""python3 run_books.py MARKDOWN_DIR PDF_DIR OUTPUT_DIR"""
import argparse
import subprocess
import sys
from pathlib import Path
from html import escape

BOOKS=[
    ("train_latyshova","Латышова","90-108","Интерпретация диаграмм скважин"),
    ("train_basniev","Басниев","474-500","Неустановившееся движение жидкости"),
    ("train_kuznetsov","Кузнецов","200-222","Природные резервуары рифов"),
    ("ctrl_vendelshtein","Вендельштейн","9-14,20-30","Параметры нефтегазовых коллекторов"),
    ("ctrl_barenblatt","Баренблатт","38-51","Движение сжимаемой жидкости"),
    ("ctrl_baraboshkin_b","Барабошкин","30-44","Дельты"),
]
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("md","pdf","out"): p.add_argument(name,type=Path)
    args=p.parse_args()
    links=[]
    for stem,author,pages,title in BOOKS:
        pdf,=args.pdf.glob(author+"*.pdf")
        subprocess.run([sys.executable,str(Path(__file__).with_name("build.py")),str(args.md/(stem+".md")),pages,str(args.out/stem),"--pdf",str(pdf),"--title",title],check=True)
        if stem in ("train_latyshova","ctrl_vendelshtein"):
            links.append("<h2>"+("Обучение" if stem.startswith("train") else "Контроль")+"</h2>")
        links.append(f'<p><a href="{stem}/index.html">{escape(author)} · {escape(title)}</a><br><small>Страницы PDF {pages}</small></p>')
    (args.out/"index.html").write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Курсы по геологии</title><style>body{max-width:48rem;margin:4rem auto;padding:0 1.3rem;background:#f7f6ef;color:#20332f;font:18px/1.5 system-ui}a{color:#006657}h1,h2{font-family:Georgia}</style><h1>Курсы по геологии</h1>'+''.join(links))
