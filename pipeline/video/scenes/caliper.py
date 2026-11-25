"""Сцена «скважина и каверномер» — одна модель состояния для разреза и кривой.

Состояние: t (время фильтрации 0..1), washout (0..1, расширение в глине), show (что видно), caliper_to (доля глубины,
до которой прорисована кривая), no_cake (бурение на нефильтрующемся растворе).
Радиус стенки r(z) и кривая каверномера d_c(z)/d_a вычисляются ОДНОЙ функцией wall_ratio(z, state) —
поэтому кривая не может разойтись с картинкой (инвариант спецификации).
"""
import math

from PIL import Image, ImageDraw

# Легенда серии (одно обозначение — одно значение): цвета пород и флюидов.
COL = {
    "bg": (15, 21, 20), "ink": (229, 236, 233), "muted": (154, 168, 163), "line": (46, 59, 56),
    "clay": (110, 122, 104), "collector": (214, 178, 92), "dense": (120, 136, 156),
    "mud": (92, 70, 52), "cake": (150, 104, 62), "filtrate": (82, 195, 191),
    "arrow": (82, 195, 191), "log": (236, 128, 128), "nominal": (154, 168, 163), "hi": (255, 255, 255),
}
LAYERS = [("clay", "глина", 0.0, 0.34), ("collector", "коллектор (песчаник)", 0.34, 0.67), ("dense", "плотная порода", 0.67, 1.0)]
CAKE = 0.12        # толщина корки, доля d_a (схема, увеличено ~20×)
WASHOUT = 0.22     # расширение в глине, доля d_a (схема)
INVADE = 1.6       # радиус проникновения, доля d_a при t = 1 (условно)


def layer_at(z):
    for key, _, a, b in LAYERS:
        if a <= z < b or (z >= 1.0 and key == "dense"):
            return key
    return "dense"


def wall_ratio(z: float, s: dict) -> float:
    """d_c / d_a на глубине z (0..1) — общая функция для разреза и каверномера."""
    kind = layer_at(z)
    if kind == "collector" and not s.get("no_cake"):
        return 1.0 - 2 * CAKE * min(1.0, s.get("t", 0)) ** 0.5   # корка растёт с фильтрацией
    if kind == "clay":
        return 1.0 + 2 * WASHOUT * s.get("washout", 0)
    return 1.0


def lerp(a, b, k):
    return a + (b - a) * k


def interp_state(prev: dict, cur: dict, p: float) -> dict:
    """Плавный переход числовых параметров от предыдущей сцены к текущей (первые 40% сцены)."""
    k = min(1.0, p / 0.4)
    k = k * k * (3 - 2 * k)
    s = dict(cur)
    for key in ("t", "washout"):
        s[key] = lerp(prev.get(key, 0), cur.get(key, 0), k)
    if "washout" in cur.get("show", []) and "washout" not in prev.get("show", []):
        s["washout"] = k
    elif "washout" in cur.get("show", []):
        s["washout"] = 1.0
    else:
        s["washout"] = 0.0
    s["caliper_to"] = lerp(prev.get("caliper_to", 0), cur.get("caliper_to", 0), min(1.0, p / 0.8)) if cur.get("caliper_to") else 0
    s["p"] = p
    return s


def arrow(d: ImageDraw.ImageDraw, x0, y, x1, col, w=5):
    d.line([(x0, y), (x1, y)], fill=col, width=w)
    sgn = 1 if x1 > x0 else -1
    d.polygon([(x1, y), (x1 - sgn * 22, y - 12), (x1 - sgn * 22, y + 12)], fill=col)


def draw(img: Image.Image, s: dict, font, small) -> None:
    W, H = img.size
    d = ImageDraw.Draw(img)
    if "true_scale" in s.get("show", []):
        return draw_true_scale(img, s, font, small)
    top, bottom = 300, 1380            # зона разреза по высоте
    sec_l, sec_r = 60, 700             # разрез
    log_l, log_r = 760, 1020           # трек каверномера
    cx = (sec_l + sec_r) // 2
    ra = 70                            # номинальный радиус ствола, px (схема)
    zpx = lambda z: top + z * (bottom - top)
    show = s.get("show", [])
    # пласты
    if "layers" in show:
        for key, name, a, b in LAYERS:
            col = COL[key]
            if s.get("highlight") and s["highlight"] != key:
                col = tuple(int(c * 0.55) for c in col)
            d.rectangle([sec_l, zpx(a), sec_r, zpx(b)], fill=col)
            d.text((sec_l + 14, zpx(a) + 12), name, font=small, fill=COL["bg"] if s.get("highlight") in (None, key) else COL["muted"])
    else:
        d.rectangle([sec_l, top, sec_r, bottom], fill=(40, 48, 46))
    # зона проникновения (только коллектор, растёт с t)
    if "invasion" in show and not s.get("no_cake"):
        rinv = ra * (1 + (INVADE - 1) * min(1, s.get("t", 0)))
        a, b = LAYERS[1][2], LAYERS[1][3]
        for side in (-1, 1):
            for i in range(24):
                k = i / 24
                x0 = cx + side * (ra + (rinv - ra) * k)
                x1 = cx + side * (ra + (rinv - ra) * (k + 1 / 24))
                alpha = 1 - k
                base = COL["collector"]
                col = tuple(int(lerp(base[j], COL["filtrate"][j], 0.75 * alpha)) for j in range(3))
                d.rectangle([min(x0, x1), zpx(a), max(x0, x1), zpx(b)], fill=col)
        d.text((cx + rinv + 10, zpx(a) + 60), "зона проникновения", font=small, fill=COL["bg"])
    # ствол: стенка из общей функции wall_ratio
    steps = 240
    left, right = [], []
    for i in range(steps + 1):
        z = i / steps
        r = ra * wall_ratio(z, s)
        left.append((cx - r, zpx(z)))
        right.append((cx + r, zpx(z)))
    d.polygon(left + right[::-1], fill=COL["mud"])
    # корка: между номиналом и фактической стенкой в коллекторе
    if "cake" in show and not s.get("no_cake"):
        a, b = LAYERS[1][2], LAYERS[1][3]
        r = ra * wall_ratio((a + b) / 2, s)
        for side in (-1, 1):
            d.rectangle([min(cx + side * r, cx + side * ra), zpx(a), max(cx + side * r, cx + side * ra), zpx(b)], fill=COL["cake"])
        d.text((cx - ra - 160, zpx(b) - 50), "корка", font=small, fill=COL["hi"])
    # номинальный диаметр (по долоту) — пунктир
    for side in (-1, 1):
        x = cx + side * ra
        for y in range(top, bottom, 26):
            d.line([(x, y), (x, y + 12)], fill=COL["nominal"], width=2)
    d.text((cx - 70, top - 44), "d долота", font=small, fill=COL["muted"])
    # стрелки давления: из скважины в коллектор
    if s.get("arrows"):
        a, b = LAYERS[1][2], LAYERS[1][3]
        ph = (s.get("p", 0) * 3) % 1
        for z in (a + 0.08, (a + b) / 2, b - 0.08):
            for side in (-1, 1):
                x0 = cx + side * (ra * 0.6)
                x1 = cx + side * (ra + 60 + 60 * ph)
                arrow(d, x0, zpx(z), x1, COL["arrow"])
        d.text((cx - 150, zpx(a) - 46), "p в скважине > p пласта", font=small, fill=COL["hi"])
    # трек каверномера: та же функция
    if "log" in show:
        d.rectangle([log_l, top, log_r, bottom], outline=COL["line"], width=2)
        d.text((log_l, top - 44), "каверномер", font=small, fill=COL["muted"])
        xr = lambda q: log_l + (q - 0.6) / 0.9 * (log_r - log_l)   # шкала d_c/d_a 0.6…1.5
        x1 = xr(1.0)
        for y in range(top, bottom, 26):
            d.line([(x1, y), (x1, y + 12)], fill=COL["nominal"], width=2)
        d.text((x1 - 30, bottom + 10), "= долото", font=small, fill=COL["muted"])
        d.text((log_l, bottom + 10), "уже", font=small, fill=COL["muted"])
        d.text((log_r - 60, bottom + 10), "шире", font=small, fill=COL["muted"])
        pts = []
        upto = s.get("caliper_to", 0)
        for i in range(int(steps * upto) + 1):
            z = i / steps
            pts.append((xr(wall_ratio(z, s)), zpx(z)))
        if len(pts) > 1:
            d.line(pts, fill=COL["log"], width=6)
    # глубина растёт вниз
    d.text((sec_l, bottom + 10), "глубина ↓", font=small, fill=COL["muted"])
    if s.get("no_cake") and "layers" in show:
        d.text((cx - 60, (zpx(LAYERS[1][2]) + zpx(LAYERS[1][3])) / 2 - 40), "?", font=font, fill=COL["hi"])


def draw_true_scale(img, s, font, small):
    """Истинный масштаб: ствол и пласт в одном масштабе — ствол почти линия, корку не видно."""
    W, H = img.size
    d = ImageDraw.Draw(img)
    top, bottom, l, r = 300, 1380, 140, 940
    d.rectangle([l, top, r, bottom], fill=COL["collector"])
    cx = (l + r) // 2
    # условно: пласт ~10 м на высоту зоны, ствол ~0.2 м — ширина пропорциональна
    px_per_m = (bottom - top) / 10
    w = 0.2 * px_per_m
    d.rectangle([cx - w / 2, top, cx + w / 2, bottom], fill=COL["mud"])
    d.text((l, bottom + 14), "истинный масштаб: по горизонтали и вертикали одинаково", font=small, fill=COL["muted"])
    d.text((cx + w + 20, (top + bottom) / 2), "ствол", font=small, fill=COL["bg"])
