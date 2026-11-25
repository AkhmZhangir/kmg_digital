"""python3 extract.py BOOK.md START END > pages.json"""
import argparse
import json
import re
from pathlib import Path


def extract(path, start, end):
    if not 1 <= start <= end:
        raise ValueError("Некорректный диапазон страниц")
    parts = re.split(r"(?m)^<!-- page (\d+) -->[ \t]*$", path.read_text(encoding="utf-8"))
    pages = {}
    for label, body in zip(parts[1::2], parts[2::2]):
        number = int(label)
        if start <= number <= end:
            if number in pages or not body.strip():
                raise ValueError(f"Повтор или пустая страница {number}")
            pages[number] = body.strip()
    missing = sorted(set(range(start, end + 1)) - pages.keys())
    if missing:
        raise ValueError(f"Отсутствуют страницы {missing}")
    return [{"source": path.name, "pdf_page": i, "ocr": pages[i]} for i in range(start, end + 1)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Извлечь страницы Markdown по номерам PDF")
    parser.add_argument("book", type=Path)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()
    print(json.dumps(extract(args.book, args.start, args.end), ensure_ascii=False, indent=2))
