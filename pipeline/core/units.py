"""Глава → единицы (абзац, заголовок, формула, таблица, рисунок, пример, задача).

Единица — минимальный кусок текста главы со страницей PDF и устойчивым id.
Таблица покрытия ТЗ строится по этим единицам.
"""
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .textnorm import looks_garbled, latin_share

PAGE = re.compile(r"(?m)^<!-- page (\d+) -->[ \t]*$")
FIG_DESC = re.compile(r"(?ms)^-{3,}[ \t]*\n+━━━.*?(?=^-{3,}[ \t]*$|\Z)(?:^-{3,}[ \t]*$)?")

KINDS = ("heading", "para", "formula", "table", "figure", "figure_desc", "example", "task", "list")


@dataclass
class Unit:
    id: str
    page: int
    kind: str
    text: str
    section: str = ""
    pages: list = field(default_factory=list)
    ocr_bad: bool = False

    def to_dict(self):
        return asdict(self)


def load_pages(md_path: Path) -> dict[int, str]:
    raw = md_path.read_text(encoding="utf-8")
    parts = PAGE.split(raw)
    pages: dict[int, str] = {}
    for label, body in zip(parts[1::2], parts[2::2]):
        pages[int(label)] = pages.get(int(label), "") + body
    return pages


def chapter_pages(pages: dict[int, str], segments: list[dict]) -> list[tuple[int, str]]:
    """Страницы главы с обрезкой по start/end внутри первой и последней страницы сегмента."""
    out: list[tuple[int, str]] = []
    for seg in segments:
        nums = [p for p in range(seg["from"], seg["to"] + 1) if p in pages]
        missing = sorted(set(range(seg["from"], seg["to"] + 1)) - set(nums))
        if missing:
            raise ValueError(f"В md нет страниц {missing}")
        chunk = [(p, pages[p]) for p in nums]
        if seg.get("start"):
            rx = re.compile(seg["start"], re.M)
            for i, (p, text) in enumerate(chunk):
                m = rx.search(text)
                if m:
                    chunk = [(p, text[m.start():])] + chunk[i + 1:]
                    break
            else:
                raise ValueError(f"Не найдено начало главы: {seg['start']}")
        if seg.get("end"):
            rx = re.compile(seg["end"], re.M)
            for i, (p, text) in enumerate(chunk):
                m = rx.search(text)
                if m:
                    chunk = chunk[:i] + ([(p, text[:m.start()])] if text[:m.start()].strip() else [])
                    break
        out.extend(chunk)
    return out


def _kind(block: str, in_tasks: bool) -> str:
    s = block.lstrip()
    if s.startswith("#"):
        return "heading"
    if s.startswith("$$") or s.startswith("\\["):
        return "formula"
    if s.startswith("|"):
        return "table"
    if re.match(r"(?i)^(\*\*)?рис(унок)?\.?\s*\d", s) or re.match(r"(?i)^(fig\.?|figure)\s*\d", s):
        return "figure"
    if re.match(r"(?i)^(\*\*)?(пример|example)\s*\d", s):
        return "example"
    if re.match(r"(?i)^(\*\*)?задач[аи]\s*$", s):
        return "heading"
    if in_tasks and re.match(r"^\d+\.\s", s):
        return "task"
    if re.match(r"^(\d+[.)]|[-•–])\s", s):
        return "list"
    return "para"


def _blocks(text: str) -> list[tuple[str, str]]:
    """Разбивает страницу на блоки: описания рисунков OCR целиком, остальное по пустым строкам."""
    out, pos = [], 0
    for m in FIG_DESC.finditer(text):
        out += [("", b) for b in re.split(r"\n\s*\n", text[pos:m.start()])]
        out.append(("figure_desc", m.group()))
        pos = m.end()
    out += [("", b) for b in re.split(r"\n\s*\n", text[pos:])]
    return [(k, b.strip()) for k, b in out if b.strip() and not re.fullmatch(r"-{3,}", b.strip())]


def split_units(chapter: list[tuple[int, str]], lang: str = "ru") -> list[Unit]:
    units: list[Unit] = []
    section, in_tasks = "", False
    counters: dict[int, int] = {}
    for page, text in chapter:
        for forced, block in _blocks(text):
            kind = forced or _kind(block, in_tasks)
            if kind == "heading":
                title = block.strip("#* \n")
                in_tasks = bool(re.match(r"(?i)^задач[аи]$", title))
                if not in_tasks:
                    section = title[:160]
            elif kind not in ("task", "list", "formula", "figure", "figure_desc", "table"):
                in_tasks = in_tasks and kind == "task"
            prev = units[-1] if units else None
            # Абзац, разорванный страницей: склеиваем с предыдущим.
            if (prev and kind == "para" and prev.kind in ("para", "list", "task") and prev.page != page
                    and not re.search(r"[.!?:»)]\s*$", prev.text) and re.match(r"[a-zа-яё(«\d]", block)):
                prev.text += " " + block
                prev.pages.append(page)
                continue
            counters[page] = counters.get(page, 0) + 1
            units.append(Unit(
                id=f"u{page:03d}-{counters[page]:02d}", page=page, kind=kind, text=block,
                section=section, pages=[page],
                ocr_bad=kind not in ("figure_desc", "formula") and looks_garbled(block, lang),
            ))
    return units


def detect_lang(chapter: list[tuple[int, str]]) -> str:
    sample = " ".join(t for _, t in chapter)[:20000]
    return "en" if latin_share(sample) > 0.6 else "ru"


def load_chapter(cfg: dict, md_dir: Path) -> list[Unit]:
    md = md_dir / cfg["md"]
    chapter = chapter_pages(load_pages(md), cfg["segments"])
    lang = cfg.get("lang") or detect_lang(chapter)
    return split_units(chapter, lang)
