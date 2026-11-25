"""Запасной рендер для проверки слоя глазами, пока нет pipeline/render.py (его делает Codex).
Одна статичная страница: шаги, абзацы со «стр. N», утверждения, задания. Не для жюри."""
import html
import json
from pathlib import Path

from .verify import iter_paras

CSS = """body{max-width:820px;margin:auto;padding:24px 16px;font:17px/1.55 system-ui;background:#f7f6ef;color:#1d2a27}
@media(prefers-color-scheme:dark){body{background:#121a18;color:#e3ebe8}.c{background:#1c2624!important}}
h1{font-size:1.7rem}h2{margin-top:2.2rem;border-top:1px solid #9aa;padding-top:1rem}.pg{color:#888;font-size:.8em}
.c{background:#fff;border-radius:8px;padding:8px 12px;margin:6px 0}.bad{color:#b23a3a}.meta{color:#677;font-size:.9em}
details{margin:.4rem 0}code{white-space:pre-wrap}"""


def _p(p):
    return f"<p>{html.escape(p['text'])} <span class=pg>· стр. {p['page']}</span></p>"


def render_preview(layer: dict, out_dir: Path) -> Path:
    h = [f"<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>{html.escape(layer['chapter']['title'][:60])}</title><style>{CSS}</style>",
         f"<h1>{html.escape(layer['chapter']['title'])}</h1><p class=meta>{html.escape(layer['chapter']['author'])}, "
         f"стр. {layer['chapter']['pages'][0]}–{layer['chapter']['pages'][1]} · модель: {html.escape(layer['chapter']['built_with']['model'])} · "
         f"предпросмотр ядра, не финальный курс</p>"]
    tasks = {}
    for t in layer["tasks"]:
        tasks.setdefault(t["node_id"], []).append(t)
    for n in layer["nodes"]:
        h.append(f"<h2>{n['order']}. {html.escape(n['title'])}</h2><p class=meta>{html.escape(n['book_title'])} · "
                 f"тип {n['difficulty']['primary']}/{n['difficulty']['secondary'] or '—'} · формат {n['format']['primary']} · "
                 f"{n['minutes']} мин · стр. {n['pages'][0]}–{n['pages'][1]}</p>")
        h += [_p(p) for p in iter_paras(n)]
        for f in n["formulas"]:
            h.append(f"<p><code>{html.escape(f['latex'])}</code> <span class=pg>· стр. {f['page']}</span></p>")
        for t in n["tables"]:
            h.append(f"<details><summary>Таблица, стр. {t['page']}</summary><code>{html.escape(t['markdown'])}</code></details>")
        for b in n["book_tasks"]:
            h.append(f"<p class=c>Задача {html.escape(b['number'])}: {html.escape(b['text'][:400])} <span class=pg>· стр. {b['page']}</span></p>")
        cl = "".join(f"<li class={'' if c['verified'] else 'bad'}>[{c['kind']}] {html.escape(c['text'])}<br><i>«{html.escape(c['quote'])}»</i> "
                     f"<span class=pg>стр. {c['page']} · {'проверено' if c['verified'] else 'НЕ проверено'}</span></li>" for c in n["claims"])
        h.append(f"<details><summary>Утверждения ({len(n['claims'])})</summary><ul>{cl}</ul></details>")
        for t in tasks.get(n["id"], []):
            h.append(f"<div class=c><b>{t['type']}</b>: {html.escape(t['question'])}<br><code>{html.escape(json.dumps({k: v for k, v in t.items() if k not in ('id', 'node_id', 'question')}, ensure_ascii=False))}</code></div>")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "preview.html"
    path.write_text("".join(h), encoding="utf-8")
    return path
