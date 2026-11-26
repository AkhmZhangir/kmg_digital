"""Универсальная сцена: всё, что на кадре, описано в спецификации (данные), код только рисует.

Нужна, чтобы новый ролик по новой теме собирался БЕЗ нового кода: тема → spec.json с "template": "generic".
Кадр делится на две синхронные панели: «разрез» (колонка слоёв + объекты) и «график» (кривые).
9:16 — панели друг под другом, 16:9 — рядом (синхронные виды). Все координаты — доли панели 0..1.

state сцены (всё необязательно; числа и одноимённые по id объекты плавно переходят от прошлой сцены):
  layers:  [{"id","label","color","top","bottom"}]              колонка пород/зон в панели «разрез»
  fills:   [{"id","color","x0","y0","x1","y1","alpha","label"}]  прямоугольники (флюид, зона, фронт)
  arrows:  [{"id","x0","y0","x1","y1","color","label"}]          стрелки (поток, давление, движение)
  markers: [{"id","x","y","r","color","label"}]                  точки/приборы, двигаются между сценами
  texts:   [{"id","x","y","text","size","color"}]                подписи (только ключевые слова)
  plot:    {"title","x_label","y_label","x_range":[a,b],"y_range":[a,b],"invert_y":bool,"log_x":bool,
            "curves":[{"id","label","color","points":[[x,y],...],"progress":0..1}],
            "hlines":[{"id","y","label","color"}], "vlines":[{"id","x","label","color"}]}
  plate:   "не в масштабе: …"   — плашка преувеличения (число обязательно)
  panels:  ["section","plot"] | ["section"] | ["plot"]   какие панели видны (по умолчанию — те, что заданы)
Цвета: имя из COL / стайлгайда («sand», «oil», «water», «GR», …) или "#RRGGBB".
Кривая — это данные или расчёт: точки кладёт в спецификацию код/человек из главы или модели, а не рисует модель-картинка.
"""
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent.parent
COL = {"bg": (15, 21, 20), "panel": (22, 30, 29), "ink": (229, 236, 233), "muted": (154, 168, 163), "line": (46, 59, 56),
       "accent": (82, 195, 191), "warn": (221, 170, 76), "red": (236, 128, 128), "white": (255, 255, 255)}


def _hex(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _load_style():
    try:
        st = json.loads((HERE / "domain" / "geology" / "official" / "styleguide.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for group in ("lithology", "fluids", "curves"):
        for k, v in (st.get(group) or {}).items():
            if isinstance(v, dict) and str(v.get("color", "")).startswith("#"):
                COL.setdefault(k, _hex(v["color"]))


_load_style()


def color(c, default="ink"):
    if isinstance(c, (list, tuple)):
        return tuple(int(x) for x in c[:3])
    if isinstance(c, str) and c.startswith("#"):
        return _hex(c)
    return COL.get(c, COL.get(default, (229, 236, 233)))


def _on(c):
    """Цвет подписи поверх заливки c: тёмный на светлом, светлый на тёмном."""
    return COL["bg"] if 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] > 140 else COL["ink"]


def _lerp(a, b, k):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return a + (b - a) * k
    if isinstance(a, list) and isinstance(b, list) and a and b and all(isinstance(x, dict) and "id" in x for x in a + b):
        prev = {x["id"]: x for x in a}
        return [_lerp(prev[x["id"]], x, k) if x["id"] in prev else x for x in b]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and all(isinstance(x, (int, float)) for x in a + b):
        return [_lerp(x, y, k) for x, y in zip(a, b)]
    if isinstance(a, dict) and isinstance(b, dict):
        return {key: (_lerp(a[key], b[key], k) if key in a else b[key]) for key in b}
    return b


def interp_state(prev: dict, cur: dict, p: float) -> dict:
    k = 0.5 - 0.5 * math.cos(math.pi * min(1.0, p / 0.6))  # переход в первые 60% сцены, дальше — пауза на чтение
    return _lerp(prev or {}, cur, k) if prev else dict(cur)


_FONTS = {}


def _f(size, bold=False):
    key = (int(size), bold)
    if key not in _FONTS:
        try:
            _FONTS[key] = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf", int(size))
        except OSError:
            try:
                _FONTS[key] = ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", int(size))
            except OSError:
                _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def _arrow(d, x0, y0, x1, y1, col, w=6):
    d.line([x0, y0, x1, y1], fill=col, width=w)
    a = math.atan2(y1 - y0, x1 - x0)
    s = 8 + 3 * w
    d.polygon([(x1, y1), (x1 - s * math.cos(a - 0.45), y1 - s * math.sin(a - 0.45)),
               (x1 - s * math.cos(a + 0.45), y1 - s * math.sin(a + 0.45))], fill=col)


def _boxes(W, H, s):
    """Прямоугольники панелей: под шапкой (y≥230) и над подписью (y≤0.74 H)."""
    want = s.get("panels") or [p for p, key in (("section", "layers"), ("plot", "plot")) if s.get(key) or
                               (p == "section" and (s.get("fills") or s.get("arrows") or s.get("markers")))] or ["section"]
    top, bottom, m = 230, int(H * 0.74) - 40, 60
    if len(want) == 1:
        return {want[0]: (m, top, W - m, bottom)}
    if W > H:  # 16:9 — рядом
        mid = W // 2
        return {want[0]: (m, top, mid - 20, bottom), want[1]: (mid + 20, top, W - m, bottom)}
    mid = (top + bottom) // 2
    return {want[0]: (m, top, W - m, mid - 15), want[1]: (m, mid + 15, W - m, bottom)}


def _section(d, box, s, base):
    x0, y0, x1, y1 = box
    X = lambda v: x0 + (x1 - x0) * float(v)
    Y = lambda v: y0 + (y1 - y0) * float(v)
    d.rectangle(box, fill=COL["panel"])
    for L in s.get("layers") or []:
        c = color(L.get("color"), "line")
        d.rectangle([x0, Y(L.get("top", 0)), x1, Y(L.get("bottom", 1))], fill=c)
        if L.get("label"):
            d.text((x0 + 16, Y(L.get("top", 0)) + 10), str(L["label"]), font=_f(base * 0.8), fill=_on(c))
    for F in s.get("fills") or []:
        a = float(F.get("alpha", 0.85))
        c = color(F.get("color"), "accent")
        mix = tuple(int(cc * a + bb * (1 - a)) for cc, bb in zip(c, COL["panel"]))
        d.rectangle([X(F.get("x0", 0)), Y(F.get("y0", 0)), X(F.get("x1", 1)), Y(F.get("y1", 1))], fill=mix)
        if F.get("label"):
            d.text((X(F.get("x0", 0)) + 10, Y(F.get("y0", 0)) + 8), str(F["label"]), font=_f(base * 0.75), fill=_on(mix))
    for A in s.get("arrows") or []:
        c = color(A.get("color"), "accent")
        _arrow(d, X(A["x0"]), Y(A["y0"]), X(A["x1"]), Y(A["y1"]), c, int(A.get("width", 6)))
        if A.get("label"):
            d.text((X(A["x1"]) + 12, Y(A["y1"]) - base * 0.5), str(A["label"]), font=_f(base * 0.75, True), fill=c)
    for M in s.get("markers") or []:
        r = float(M.get("r", 0.02)) * (x1 - x0)
        cx, cy = X(M["x"]), Y(M["y"])
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color(M.get("color"), "white"))
        if M.get("label"):
            d.text((cx + r + 10, cy - base * 0.5), str(M["label"]), font=_f(base * 0.8, True), fill=COL["ink"])


def _plot(d, box, P, base):
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=COL["panel"])
    pl, pr, pt, pb = x0 + base * 3.2, x1 - 24, y0 + base * 1.8, y1 - base * 2.2
    xa, xb = P.get("x_range") or [0, 1]
    ya, yb = P.get("y_range") or [0, 1]
    logx = bool(P.get("log_x"))

    def X(v):
        if logx:
            v, a, b = math.log10(max(float(v), 1e-9)), math.log10(max(xa, 1e-9)), math.log10(max(xb, 1e-9))
        else:
            a, b = xa, xb
        return pl + (pr - pl) * (float(v) - a) / ((b - a) or 1)

    def Y(v):
        k = (float(v) - ya) / ((yb - ya) or 1)
        return pt + (pb - pt) * k if P.get("invert_y") else pb - (pb - pt) * k

    d.rectangle([pl, pt, pr, pb], outline=COL["line"], width=2)
    if P.get("title"):
        d.text((x0 + 16, y0 + 10), str(P["title"]), font=_f(base * 0.9, True), fill=COL["ink"])
    if P.get("x_label"):
        d.text((pl, pb + base * 0.5), str(P["x_label"]), font=_f(base * 0.75), fill=COL["muted"])
    if P.get("y_label"):
        d.text((x0 + 10, pt), str(P["y_label"]), font=_f(base * 0.7), fill=COL["muted"])
    for g in P.get("hlines") or []:
        c = color(g.get("color"), "muted")
        d.line([pl, Y(g["y"]), pr, Y(g["y"])], fill=c, width=3)
        if g.get("label"):
            d.text((pl + 10, Y(g["y"]) - base * 0.95), str(g["label"]), font=_f(base * 0.7), fill=c)
    for g in P.get("vlines") or []:
        c = color(g.get("color"), "muted")
        d.line([X(g["x"]), pt, X(g["x"]), pb], fill=c, width=3)
        if g.get("label"):
            d.text((X(g["x"]) + 8, pt + 6), str(g["label"]), font=_f(base * 0.7), fill=c)
    ly = pt + 10
    for C in P.get("curves") or []:
        pts = [(X(x), Y(y)) for x, y in C.get("points") or []]
        n = max(0, min(len(pts), int(round(len(pts) * float(C.get("progress", 1.0))))))
        c = color(C.get("color"), "red")
        if n >= 2:
            d.line(pts[:n], fill=c, width=int(C.get("width", 6)), joint="curve")
        if C.get("label"):
            d.text((pr - base * 7, ly), str(C["label"]), font=_f(base * 0.75, True), fill=c)
            ly += base * 1.1


def draw(img: Image.Image, s: dict, font, small) -> None:
    W, H = img.size
    d = ImageDraw.Draw(img)
    base = 34 if H > W else 26
    boxes = _boxes(W, H, s)
    if "section" in boxes:
        _section(d, boxes["section"], s, base)
    if "plot" in boxes and s.get("plot"):
        _plot(d, boxes["plot"], s["plot"], base)
    for T in s.get("texts") or []:
        d.text((W * float(T.get("x", 0.1)), H * float(T.get("y", 0.2))), str(T["text"]),
               font=_f(T.get("size", base * 1.4), True), fill=color(T.get("color"), "ink"))
