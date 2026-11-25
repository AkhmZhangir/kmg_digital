"""Извлечение исходных единиц с сохранением ссылок на документ."""
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

PAGE = re.compile(r"(?m)^<!-- page (\d+) -->[ \t]*$")
FORMATS = {".pdf", ".docx", ".md", ".txt"}
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
LIMIT = 100


def numbers(value):
    if not value:
        return None
    if not re.fullmatch(r"\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*", value):
        raise ValueError("Укажите страницы или блоки в формате 1–5, 8 (используйте дефис).")
    selected = set()
    for part in value.split(","):
        ends = list(map(int, part.split("-")))
        start, end = ends[0], ends[-1]
        if not 1 <= start <= end or end - start >= LIMIT:
            raise ValueError(f"Выберите от 1 до {LIMIT} страниц или блоков за сборку.")
        selected.update(range(start, end + 1))
    if len(selected) > LIMIT:
        raise ValueError(f"Выберите до {LIMIT} страниц или блоков за сборку.")
    return sorted(selected)


def select(available, selected):
    ids = selected or list(available)[:LIMIT + 1]
    if len(ids) > LIMIT:
        raise ValueError(f"В документе больше {LIMIT} страниц или блоков. Укажите диапазон.")
    if any(number not in available for number in ids):
        raise ValueError(f"В документе отсутствуют выбранные страницы или блоки. Последний номер: {max(available, default=0)}.")
    return ids


def read_docx(path):
    with ZipFile(path) as doc:
        member = doc.getinfo("word/document.xml")
        if member.file_size > 24 * 1024 * 1024:
            raise ValueError("Текст DOCX слишком большой. Выделите нужную главу в отдельный файл.")
        body = ET.fromstring(doc.read(member)).find(WORD + "body")
    if body is None:
        raise ValueError("В документе DOCX отсутствует основной текст.")
    blocks = []
    for element in body:
        if element.tag == WORD + "p":
            blocks.append("".join(t.text or "" for t in element.iter(WORD + "t")))
        elif element.tag == WORD + "tbl":
            rows = []
            for row in element.findall(WORD + "tr"):
                cells = [" ".join(t.text or "" for t in cell.iter(WORD + "t")) for cell in row.findall(WORD + "tc")]
                rows.append("| " + " | ".join(cells) + " |")
            blocks.append("\n".join(rows))
    return "\n\n".join(filter(str.strip, blocks))


def read_pdf(path, selected, force_ocr=False):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError("Для PDF установите зависимость из pipeline/requirements.txt.") from None
    reader = PdfReader(path)
    ids = select(range(1, len(reader.pages) + 1), selected)
    pages = {number: "" if force_ocr else reader.pages[number - 1].extract_text() or "" for number in ids}
    missing = [number for number, text in pages.items() if sum(map(str.isalpha, text)) < 80]
    if missing:
        pages.update(recognize_pdf(path, missing))
    return pages


def recognize_pdf(path, ids):
    if platform.system() == "Darwin" and shutil.which("swift"):
        with tempfile.TemporaryDirectory() as cache:
            result = subprocess.run(
                ["swift", "-module-cache-path", cache, str(Path(__file__).with_name("ocr.swift")),
                 str(path), *map(str, ids)],
                capture_output=True, text=True, timeout=600,
            )
        texts = result.stdout.split("\f")[:-1]
        if result.returncode == 0 and len(texts) == len(ids):
            return dict(zip(ids, texts))
    if shutil.which("pdftoppm") and shutil.which("tesseract"):
        headings = {}
        with tempfile.TemporaryDirectory() as folder:
            prefix = str(Path(folder) / "page")
            for number in ids:
                subprocess.run(["pdftoppm", "-f", str(number), "-l", str(number), "-r", "190",
                                "-singlefile", "-png", str(path), prefix],
                               check=True, capture_output=True, timeout=60)
                result = subprocess.run(["tesseract", prefix + ".png", "stdout", "-l", "rus+eng"],
                                        check=True, capture_output=True, text=True, timeout=90)
                headings[number] = result.stdout
        return headings
    raise ValueError("PDF содержит сканы. Для OCR нужен Swift на macOS либо Poppler и Tesseract с rus+eng. Можно загрузить готовый Markdown.")


def text_blocks(text):
    blocks = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        parts = re.findall(r"[\s\S]{1,4200}(?=\s|$)|[\s\S]{1,4200}", paragraph)
        for part in parts:
            if current and len(current) + len(part) > 5500:
                blocks.append(current)
                current = ""
            current = (current + "\n\n" + part).strip()
    if current:
        blocks.append(current)
    return blocks


def load_source(path, ranges="", force_ocr=False):
    kind = path.suffix.lower()
    selected = numbers(ranges)
    if kind == ".pdf":
        pages = read_pdf(path, selected, force_ocr)
        label = "PDF-стр."
    elif kind in FORMATS:
        source = read_docx(path) if kind == ".docx" else path.read_text(encoding="utf-8-sig")
        parts = PAGE.split(source)
        if len(parts) > 1:
            keys = [int(number) for number in parts[1::2]]
            if len(set(keys)) != len(keys):
                raise ValueError("В исходнике есть повторяющиеся метки страниц.")
            available = dict(zip(keys, parts[2::2]))
            label = "PDF-стр."
        else:
            available = dict(enumerate(text_blocks(source), 1))
            label = "Блок источника"
        pages = {number: available[number] for number in select(available, selected)}
    else:
        raise ValueError("Загрузите PDF, DOCX, Markdown или TXT.")
    if not pages:
        raise ValueError("В документе нет читаемого текста.")
    return {number: {"pdf_page": number, "ocr": text.strip()} for number, text in pages.items()}, label
