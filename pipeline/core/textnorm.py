"""Нормализация текста для сверки цитат и чисел с OCR-источником."""
import re
import unicodedata
from difflib import SequenceMatcher

# Латинские буквы, которые OCR путает с кириллицей (для «скелета» строки).
_LOOKALIKE = str.maketrans("aceopxyABCEHKMOPTXy", "асеорхуАВСЕНКМОРТХу")
_MD = re.compile(r"\\[a-zA-Z]+|[*_#`>|~^{}\\$]")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def skeleton(text: str) -> str:
    """Только буквы и цифры в нижнем регистре: устойчиво к пробелам, переносам, разметке, LaTeX."""
    t = unicodedata.normalize("NFKC", text)
    t = _MD.sub(" ", t)
    t = t.translate(_LOOKALIKE).lower().replace("ё", "е")
    return "".join(ch for ch in t if ch.isalnum())


def quote_match(quote: str, source: str, min_len: int = 15) -> tuple[str, float]:
    """Ищет цитату в источнике. Возвращает ('exact'|'fuzzy'|'none', доля совпадения)."""
    q, s = skeleton(quote), skeleton(source)
    if len(q) < min_len:
        return "none", 0.0
    if q in s:
        return "exact", 1.0
    m = SequenceMatcher(None, q, s, autojunk=False)
    longest = m.find_longest_match(0, len(q), 0, len(s)).size
    share = longest / len(q)
    if _blocks_local(m, len(q)):
        share = max(share, sum(b.size for b in m.get_matching_blocks() if b.size >= 6) / len(q))
    return ("fuzzy" if share >= 0.9 else "none"), round(share, 3)


def _blocks_local(m: SequenceMatcher, qlen: int) -> bool:
    """Совпадающие куски должны лежать в источнике компактно, а не по всей главе."""
    blocks = [b for b in m.get_matching_blocks() if b.size >= 6]
    if not blocks:
        return False
    span = blocks[-1].b + blocks[-1].size - blocks[0].b
    return span <= qlen * 1.3


def numbers(text: str) -> set[str]:
    """Числа текста в каноническом виде: '1,50' → '1.5', '−3' → '-3'."""
    out = set()
    for raw in _NUM.findall(unicodedata.normalize("NFKC", text)):
        v = raw.replace(",", ".")
        try:
            f = float(v)
        except ValueError:
            continue
        out.add(("%f" % f).rstrip("0").rstrip("."))
    return out


def latin_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum("a" <= c.lower() <= "z" for c in letters) / len(letters)


def looks_garbled(text: str, lang: str = "ru") -> bool:
    """Кириллица, распознанная латиницей: «OIIpeJIeHTb». Для русских глав."""
    if lang != "ru" or len(text) < 40:
        return False
    plain = re.sub(r"\\\(.*?\\\)|\$.*?\$|\[.*?\]", " ", text)
    words = re.findall(r"[A-Za-z]{4,}", plain)
    if not words:
        return False
    odd = [w for w in words if re.search(r"II|JI|[a-z][A-Z]{2}|[A-Z][a-z][A-Z]", w)]
    return latin_share(plain) > 0.35 and len(odd) >= 3
