"""Иллюстрации шагов кодом — классы A/B из ТЗ, без генеративных моделей.

Шаблоны (выбираются по содержимому узла):
  steps     — «по шагам»: процедура автора блоками со стрелками                (класс B, «схема»)
  signal    — «сигнал → вывод»: наблюдения слева, выводы справа, допущения снизу (класс B, «схема»)
  pressure  — расчёт: распределение давления p(x, t) при упругом режиме (erfc)   (класс B, «симуляция»)
  links     — карта шага: на что опирается и куда ведёт                         (класс B, «схема»)
SVG сам переключает тему через prefers-color-scheme. Текст в SVG — только из узла (подписи из книги).
"""
import html
import math
import re
from pathlib import Path

STYLE = """<style>
.bg{fill:#ffffff}.box{fill:#eef3f1;stroke:#56625d;stroke-width:1.2}.obs{fill:#e3f1e8;stroke:#2c8350}.inf{fill:#e4ecf7;stroke:#2f65a8}
.ass{fill:#f7e6ee;stroke:#b83a72}.t{font:14px system-ui,sans-serif;fill:#17211e}.s{font:12px system-ui,sans-serif;fill:#56625d}
.h{font:600 15px system-ui,sans-serif;fill:#17211e}.ar{stroke:#0c6b6b;stroke-width:2;fill:none;marker-end:url(#a)}.ax{stroke:#56625d;stroke-width:1}
.c1{stroke:#0c6b6b;stroke-width:2.2;fill:none}.c2{stroke:#9c6c12;stroke-width:2.2;fill:none}.c3{stroke:#b23a3a;stroke-width:2.2;fill:none}
.tag{font:11px ui-monospace,monospace;fill:#56625d}
@media (prefers-color-scheme:dark){.bg{fill:#172020}.box{fill:#1f2a28;stroke:#9aa8a3}.obs{fill:#143424}.inf{fill:#14253a}.ass{fill:#3a1a2a}
.t,.h{fill:#e5ecE9}.s,.tag{fill:#9aa8a3}.ar{stroke:#52c3bf}.ax{stroke:#9aa8a3}.c1{stroke:#52c3bf}.c2{stroke:#ddaa4c}.c3{stroke:#ec8080}}
</style><defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#0c6b6b"/></marker></defs>"""


def _wrap(text: str, width: int) -> list[str]:
    text = re.sub(r"\\\(|\\\)|\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", text)
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def _text(x, y, lines, cls="t", lh=18):
    return "".join(f'<text x="{x}" y="{y + i * lh}" class="{cls}">{html.escape(l)}</text>' for i, l in enumerate(lines))


def _svg(w, h, body, label, provenance):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(label)}">'
            f'{STYLE}<rect class="bg" width="{w}" height="{h}" rx="10"/>{body}'
            f'<text x="{w - 10}" y="{h - 8}" text-anchor="end" class="tag">{html.escape(provenance)}</text></svg>')


def steps_svg(title: str, steps: list[str]) -> str:
    w, y, body = 640, 40, [_text(20, 26, [title[:70]], "h")]
    for i, s in enumerate(steps[:6]):
        lines = _wrap(s, 70)[:3]
        h = 16 + 18 * len(lines)
        body.append(f'<rect class="box" x="20" y="{y}" width="600" height="{h}" rx="8"/>')
        body.append(f'<text x="34" y="{y + 22}" class="h">{i + 1}</text>' + _text(58, y + 22, lines))
        y += h
        if i < min(len(steps), 6) - 1:
            body.append(f'<path class="ar" d="M320 {y + 2} L320 {y + 20}"/>')
            y += 24
    return _svg(w, y + 30, "".join(body), "Схема шагов: " + title, "схема · по тексту книги")


def signal_svg(title: str, obs: list[str], inf: list[str], ass: list[str]) -> str:
    w, body = 760, [_text(20, 26, [title[:80]], "h"),
                    '<text x="20" y="54" class="s">наблюдение (что видно в данных)</text>',
                    '<text x="420" y="54" class="s">вывод (интерпретация)</text>']
    y_l = y_r = 66
    for s in obs[:4]:
        lines = _wrap(s, 40)[:3]
        h = 14 + 18 * len(lines)
        body.append(f'<rect class="obs" x="20" y="{y_l}" width="320" height="{h}" rx="8"/>' + _text(32, y_l + 20, lines))
        y_l += h + 10
    for s in inf[:4]:
        lines = _wrap(s, 40)[:3]
        h = 14 + 18 * len(lines)
        body.append(f'<rect class="inf" x="420" y="{y_r}" width="320" height="{h}" rx="8"/>' + _text(432, y_r + 20, lines))
        y_r += h + 10
    mid = 66 + (min(y_l, y_r) - 66) / 2
    body.append(f'<path class="ar" d="M346 {mid} L414 {mid}"/>')
    y = max(y_l, y_r) + 6
    for s in ass[:2]:
        lines = _wrap(s, 90)[:2]
        h = 14 + 18 * len(lines)
        body.append(f'<rect class="ass" x="20" y="{y}" width="720" height="{h}" rx="8"/>'
                    + _text(32, y + 20, ["Допущение: " + lines[0]] + lines[1:]))
        y += h + 8
    return _svg(w, y + 26, "".join(body), "Схема «сигнал → вывод»: " + title, "схема · наблюдение отделено от вывода")


def pressure_svg(title: str) -> str:
    """Безразмерное решение линейной задачи упругого режима: (p0 − p)/(p0 − pг) = erfc(x / 2√(κt))."""
    w, h, x0, y0, pw, ph = 640, 360, 60, 40, 540, 250
    body = [_text(20, 26, [title[:70]], "h"),
            f'<path class="ax" d="M{x0} {y0} L{x0} {y0 + ph} L{x0 + pw} {y0 + ph}"/>',
            f'<text x="{x0 + pw}" y="{y0 + ph + 22}" text-anchor="end" class="s">расстояние от галереи x, м (условно)</text>',
            f'<text x="{x0 - 8}" y="{y0 + 4}" text-anchor="end" class="s">p₀</text>',
            f'<text x="{x0 - 8}" y="{y0 + ph}" text-anchor="end" class="s">pг</text>']
    for t, cls in ((1, "c1"), (4, "c2"), (16, "c3")):
        pts = []
        for i in range(101):
            x = i / 100 * 10
            drop = math.erfc(x / (2 * math.sqrt(t)))  # доля понижения давления
            pts.append(f"{x0 + i / 100 * pw:.1f},{y0 + drop * ph:.1f}")
        body.append(f'<polyline class="{cls}" points="{" ".join(pts)}"/>')
        lx = x0 + min(0.95, 2 * math.sqrt(t) / 10) * pw
        body.append(f'<text x="{lx:.0f}" y="{y0 + ph * 0.42 + t:.0f}" class="s">κt = {t}</text>')
    body.append(f'<text x="{x0 + 8}" y="{y0 + ph + 44}" class="s">Воронка депрессии расширяется со временем: зона понижения ~ 2√(κt), а не с постоянной скоростью.</text>')
    return _svg(w, h + 30, "".join(body), "Расчёт: распределение давления в пласте в разные моменты времени", "симуляция · erfc-решение, без масштаба")


def links_svg(title: str, before: list[str], after: list[str]) -> str:
    w, h = 720, 60 + 46 * max(1, len(before), len(after))
    cy = h / 2
    body = [f'<rect class="inf" x="250" y="{cy - 30}" width="220" height="60" rx="10"/>'
            + _text(262, cy - 6, _wrap(title, 26)[:2], "h")]
    for i, t in enumerate(before[:5]):
        y = 30 + i * 46
        body.append(f'<rect class="box" x="20" y="{y}" width="190" height="36" rx="8"/>' + _text(30, y + 23, _wrap(t, 24)[:1], "s")
                    + f'<path class="ar" d="M212 {y + 18} L246 {cy}"/>')
    for i, t in enumerate(after[:5]):
        y = 30 + i * 46
        body.append(f'<rect class="box" x="510" y="{y}" width="190" height="36" rx="8"/>' + _text(520, y + 23, _wrap(t, 24)[:1], "s")
                    + f'<path class="ar" d="M472 {cy} L506 {y + 18}"/>')
    body.append(f'<text x="20" y="18" class="s">опирается на</text><text x="700" y="18" text-anchor="end" class="s">нужен для</text>')
    return _svg(w, h, "".join(body), "Карта шага: " + title, "схема · связи шагов курса")


def illustrate(layer: dict, out_dir: Path) -> int:
    media = out_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    titles = {n["id"]: n["title"] for n in layer["nodes"]}
    after = {}
    for n in layer["nodes"]:
        for l in n["links"]:
            after.setdefault(l["to"], []).append(n["id"])
    count = 0
    for n in layer["nodes"]:
        made = []
        claims = {c["id"]: c for c in n["claims"]}
        text = " ".join(p["text"] for p in (n["how_it_works"] + n["summary"]))
        if len(n["steps"]) >= 2:
            made.append(("steps", steps_svg(n["title"], [p["text"] for p in n["steps"]]),
                         "Порядок действий по тексту автора", "B", "схема"))
        obs = [c["text"] for c in claims.values() if c["kind"] == "observation" and c.get("verified")]
        inf = [c["text"] for c in claims.values() if c["kind"] == "inference" and c.get("verified")]
        ass = [c["text"] for c in claims.values() if c["kind"] == "assumption"]
        if obs and inf and n["difficulty"]["primary"] in ("И", "Н", "Р", "Пр"):
            made.append(("signal", signal_svg(n["title"], obs, inf, ass), "Что наблюдаем и что из этого выводим", "B", "схема"))
        if re.search(r"(?i)пьезопроводн|упруг\w* режим|неустановивш|нестационарн", text) and n["difficulty"]["primary"] in ("Ф", "М"):
            made.append(("pressure", pressure_svg(n["title"]), "Расчёт: как понижение давления расходится по пласту", "B", "симуляция"))
        if not made:
            before = [titles[l["to"]] for l in n["links"] if l["to"] in titles]
            made.append(("links", links_svg(n["title"], before or ["начало главы"], [titles[x] for x in after.get(n["id"], [])] or ["следующие шаги"]),
                         "Карта шага: на что он опирается и куда ведёт", "B", "схема"))
        n["illustrations"] = []
        for j, (kind, svg, caption, cls, prov) in enumerate(made, 1):
            name = f"{re.sub(r'[^a-z0-9.-]+', '-', n['id'].lower())}-{kind}.svg"
            (media / name).write_text(svg, encoding="utf-8")
            n["illustrations"].append({"id": f"{n['id']}.ill{j}", "class": cls, "src": f"media/{name}", "alt": caption + ": " + n["title"],
                                       "caption": caption, "provenance": prov, "redrawn_from": None, "source_url": None})
            count += 1
    return count
