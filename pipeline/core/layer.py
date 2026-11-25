"""Единицы главы → учебный слой (contract/LAYER_FORMAT.md v1.0).

Этапы: outline (граф понятий по кускам главы) → порядок и части (детерминированно) →
заполнение узлов (LLM + проверка цитат + один повтор с ошибками) → задания и карточки → покрытие.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .llm import LLM, LLMError
from .textnorm import numbers, skeleton
from .verify import check_claim, check_task, iter_paras, node_plain_text, para_number_issues

HERE = Path(__file__).resolve().parent.parent
OUTLINE_BUDGET = 18000      # знаков текста единиц на один запрос outline
NODE_BUDGET = 12000         # знаков на узел; больше — узел делится
FIG_DESC_CUT = 500
TASK_CYCLE = ["single", "cloze", "order", "multi", "calc"]
VIDEO_KEYS = ("time_change", "invisible_visible", "scale_jump", "counterintuitive", "cause_effect")


def _prompt(name: str, pack: dict) -> str:
    return (HERE / "prompts" / f"{name}.txt").read_text(encoding="utf-8").format(audience=pack["audience"])


def _unit_view(u: dict, full: bool = True) -> dict:
    text = u["text"]
    if u["kind"] == "figure_desc":
        text = "[Автоописание рисунка, не текст автора — не цитировать] " + text[: (2000 if full else FIG_DESC_CUT)]
    if u.get("ocr_bad"):
        text = "[OCR повреждён — сверить по скану] " + text
    return {"id": u["id"], "kind": u["kind"], "page": u["page"], "section": u["section"], "text": text}


def _ask(llm: LLM, system: str, payload: dict, task: str, log) -> dict:
    """Запрос к модели с повтором; если модель так и не дала разборчивый ответ — выдержка из книги (mock) с пометкой."""
    for temp in (0.2, 0.5):
        try:
            return llm.chat_json(system, payload, temperature=temp, task=task)
        except (LLMError, ValueError) as e:
            log(f"  {task}: ответ модели не разобран ({type(e).__name__}: {str(e)[:80]}), повтор")
    from . import mock
    log(f"  {task}: используем выдержку из книги вместо ответа модели")
    out = mock.respond(task, payload)
    out["_fallback"] = True
    return out


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:48] or "node"


def _clean_title(s: str) -> str:
    s = re.sub(r"[#*_]+", "", s).strip()
    if s.isupper():
        s = s.capitalize()
    return re.sub(r"\s+", " ", s)


# ---------------------------------------------------------------- outline

def outline(units: list[dict], llm: LLM, pack: dict, cfg: dict, log) -> tuple[list[dict], list[dict]]:
    chunks, cur, size = [], [], 0
    for u in units:
        n = min(len(u["text"]), FIG_DESC_CUT) if u["kind"] == "figure_desc" else len(u["text"])
        if cur and size + n > OUTLINE_BUDGET:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(u)
        size += n
    if cur:
        chunks.append(cur)
    system = _prompt("outline", pack)
    nodes, skip, seen = [], [], set()
    for ci, chunk in enumerate(chunks):
        payload = {"task": "outline", "chunk": ci,
                   "chapter": {k: cfg.get(k) for k in ("title", "book", "author", "year")},
                   "chapter_types": cfg.get("types"),
                   "difficulty_types": {k: v["name"] for k, v in pack["difficulty_types"].items()},
                   "units": [_unit_view(u, full=False) for u in chunk]}
        out = _ask(llm, system, payload, "outline", log)
        ids = {u["id"] for u in chunk}
        taken = set()
        for raw in out.get("nodes") or []:
            us = [x for x in raw.get("units") or [] if x in ids and x not in taken]
            if not us:
                continue
            taken.update(us)
            key = _slug(str(raw.get("key") or raw.get("title") or "node"))
            while key in seen:
                key += "-x"
            seen.add(key)
            diff = raw.get("difficulty") or {}
            prim = diff.get("primary") if diff.get("primary") in pack["difficulty_types"] else (cfg.get("types") or ["И"])[0]
            sec = diff.get("secondary") if diff.get("secondary") in pack["difficulty_types"] else None
            nodes.append({"key": key, "raw_key": raw.get("key"), "title": str(raw.get("title") or "").strip(),
                          "book_title": str(raw.get("book_title") or "").strip(), "units": us,
                          "difficulty": {"primary": prim, "secondary": sec}, "threshold": bool(raw.get("threshold")),
                          "prereq_raw": [str(k) for k in raw.get("prereq_keys") or []],
                          "new_terms": [str(t) for t in raw.get("new_terms") or []],
                          "video_criteria": [v for v in raw.get("video_criteria") or [] if v in VIDEO_KEYS], "chunk": ci})
        for s in out.get("skip") or []:
            if s.get("unit") in ids and s["unit"] not in taken and str(s.get("reason", "")).strip():
                skip.append({"unit": s["unit"], "reason": str(s["reason"])})
                taken.add(s["unit"])
        # Единицы, которые модель не разметила: заголовки — пропуск, прочее — к соседнему узлу.
        chunk_nodes = [n for n in nodes if n["chunk"] == ci]
        owner = {x: n for n in chunk_nodes for x in n["units"]}
        last = None
        for u in chunk:
            if u["id"] in taken:
                last = owner.get(u["id"], last)
                continue
            if u["kind"] == "heading":
                skip.append({"unit": u["id"], "reason": "заголовок раздела"})
            else:
                target = last or next((owner[x["id"]] for x in chunk if x["id"] in owner), None)
                if target is None:
                    target = {"key": _slug(f"part-{ci}-{u['id']}"), "raw_key": None, "title": _clean_title(u["section"])[:60],
                              "book_title": u["section"], "units": [], "difficulty": {"primary": (cfg.get("types") or ["И"])[0], "secondary": None},
                              "threshold": False, "prereq_raw": [], "new_terms": [], "video_criteria": [], "chunk": ci}
                    nodes.append(target)
                    owner[u["id"]] = target
                target["units"].append(u["id"])
                target.setdefault("auto_units", []).append(u["id"])
        log(f"outline: кусок {ci + 1}/{len(chunks)} → {len(chunk_nodes)} узлов")
    # Ключи предпосылок модели → наши ключи.
    alias = {}
    for n in nodes:
        alias[str(n["raw_key"])] = n["key"]
        alias[n["key"]] = n["key"]
    for n in nodes:
        n["prereqs"] = sorted({alias[k] for k in n.pop("prereq_raw") if k in alias and alias[k] != n["key"]})
    return nodes, skip


def split_large(nodes: list[dict], by_id: dict) -> list[dict]:
    out = []
    for n in nodes:
        n["units"].sort(key=lambda x: list(by_id).index(x))
        size = sum(len(by_id[x]["text"]) for x in n["units"])
        if size <= NODE_BUDGET or len(n["units"]) < 2:
            out.append(n)
            continue
        parts, cur, s = [], [], 0
        for x in n["units"]:
            if cur and s + len(by_id[x]["text"]) > NODE_BUDGET:
                parts.append(cur)
                cur, s = [], 0
            cur.append(x)
            s += len(by_id[x]["text"])
        parts.append(cur)
        for i, us in enumerate(parts, 1):
            m = dict(n, units=us, key=f"{n['key']}-{i}", title=f"{n['title']} ({i}/{len(parts)})",
                     prereqs=list(n["prereqs"]) + ([f"{n['key']}-{i - 1}"] if i > 1 else []))
            out.append(m)
        for other in nodes:
            if n["key"] in other.get("prereqs", []):
                other["prereqs"] = [k for k in other["prereqs"] if k != n["key"]] + [f"{n['key']}-{len(parts)}"]
    return out


def order_nodes(nodes: list[dict], by_id: dict) -> list[dict]:
    """Порядок книги, поправленный предпосылками (устойчивая топологическая сортировка)."""
    pos = {x: i for i, x in enumerate(by_id)}
    for n in nodes:
        n["_pos"] = min(pos[x] for x in n["units"])
    keys = {n["key"]: n for n in nodes}
    done, out = set(), []
    pending = sorted(nodes, key=lambda n: n["_pos"])
    while pending:
        for n in pending:
            if all(p in done or p not in keys for p in n["prereqs"]):
                break
        else:
            n = pending[0]  # цикл в предпосылках — берём по книге
        pending.remove(n)
        done.add(n["key"])
        out.append(n)
    return out


# ---------------------------------------------------------------- node fill

def _route(node: dict, pack: dict, reason: str) -> dict:
    prim = node["difficulty"]["primary"]
    crit = node.get("video_criteria") or []
    names = [pack["video_criteria"][c] for c in crit]
    if len(crit) >= 2 and prim in ("М", "И", "В"):
        fmt = "short"
    elif len(crit) >= 2 and prim in ("Н", "Пр", "П"):
        fmt = "long"
    else:
        fmt = pack["difficulty_types"][prim]["default_format"]
        if fmt in ("short", "long") and len(crit) < 2:
            fmt = "interactive"
    why = f"Тип «{pack['difficulty_types'][prim]['name']}»"
    why += f"; критерии видеоёмкости: {', '.join(names)}" if names else "; критериев видеоёмкости нет"
    if reason:
        why += f". {reason}"
    return {"primary": fmt, "reason": why, "scene_template": pack["difficulty_types"][prim]["scene_template"]}


def _norm_para(p, claim_map: dict, page_of: dict, default_page: int) -> dict | None:
    if isinstance(p, str):
        p = {"text": p, "claims": []}
    if not isinstance(p, dict) or not str(p.get("text", "")).strip():
        return None
    cl = [claim_map[c] for c in p.get("claims") or [] if c in claim_map]
    page = page_of.get(cl[0], default_page) if cl else default_page
    return {"text": str(p["text"]).strip(), "claims": cl, "page": page, "by": "model"}


def fill_node(node: dict, idx: int, chapter_key: str, by_id: dict, llm: LLM, pack: dict,
              known_terms: list[str], log) -> tuple[dict, list[dict], list[dict]]:
    units = [by_id[x] for x in node["units"]]
    payload = {"task": "node", "audience": pack["audience"],
               "node": {"title": node["title"], "book_title": node["book_title"],
                        "difficulty": {k: (pack["difficulty_types"][v]["name"] if v else None) for k, v in node["difficulty"].items()}},
               "units": [_unit_view(u) for u in units], "known_terms": known_terms[-80:],
               "misconceptions": pack["misconceptions"], "it_bridges": pack["it_bridges"]}
    system = _prompt("node", pack)
    out = _ask(llm, system, payload, "node", log)
    bad = _bad_claims(out, by_id)
    if bad and not llm.is_mock:
        payload["previous_answer"] = out
        payload["errors"] = [f"{c}: {why}" for c, why in bad.items()] + [
            "Исправь цитаты: они должны быть ДОСЛОВНЫМИ кусками указанной единицы. Остальное не меняй."]
        out2 = _ask(llm, system, payload, "node-fix", log)
        if len(_bad_claims(out2, by_id)) < len(bad):
            out = out2
        log(f"  узел {node['key']}: повтор из-за {len(bad)} цитат")
    nid = f"{chapter_key}.{node['key']}"
    claim_map, claims, page_of = {}, [], {}
    for i, c in enumerate(out.get("claims") or [], 1):
        if not isinstance(c, dict):
            continue
        new = f"{node['key']}.c{i}"
        claim_map[str(c.get("id"))] = new
        cl = {"id": new, "kind": c.get("kind") if c.get("kind") in ("observation", "inference", "assumption") else "inference",
              "text": str(c.get("text", "")).strip(), "quote": str(c.get("quote", "")).strip(),
              "unit": c.get("unit"), "page": None, "by": "model"}
        ok, _ = check_claim(cl, by_id)
        cl["verified"] = ok
        cl["page"] = by_id[cl["unit"]]["page"] if cl["unit"] in by_id else units[0]["page"]
        page_of[new] = cl["page"]
        claims.append(cl)
    p0 = units[0]["page"]
    P = lambda lst: [x for x in (_norm_para(p, claim_map, page_of, p0) for p in (lst or [])) if x]
    ex_out = []
    for ex in out.get("examples") or []:
        if not isinstance(ex, dict):
            continue
        u = by_id.get(ex.get("unit"))
        ex_out.append({"title": str(ex.get("title") or "Пример"), "page": u["page"] if u else p0, "figure": ex.get("figure"),
                       "condition": P(ex.get("condition")), "solution": P(ex.get("solution")), "result": P(ex.get("result"))})
    formulas = []
    for f in out.get("formulas") or []:
        if isinstance(f, dict) and f.get("latex"):
            u = by_id.get(f.get("unit"))
            formulas.append({"latex": str(f["latex"]).strip("$ "), "page": u["page"] if u else p0,
                             "vars": [v for v in f.get("vars") or [] if isinstance(v, dict)]})
    mis = out.get("misconception")
    mis = {"wrong": str(mis.get("wrong", "")).strip(), "right": P(mis.get("right"))} if isinstance(mis, dict) and mis.get("wrong") else None
    dm = out.get("data_meaning")
    dm = ({"input": str(dm.get("input", "")), "output": str(dm.get("output", "")), "breaks": P(dm.get("breaks")),
           "hypotheses": P(dm.get("hypotheses"))} if isinstance(dm, dict) and (dm.get("input") or dm.get("output")) else None)
    an = out.get("analogy")
    an = {"text": str(an.get("text", "")), "breaks_where": str(an.get("breaks_where", ""))} if isinstance(an, dict) and an.get("text") else None
    layers = out.get("layers") if isinstance(out.get("layers"), dict) else {}
    # Таблицы и задачи книги — детерминированно из единиц (целиком, как в книге).
    tables = [{"caption": "", "page": u["page"], "markdown": u["text"], "ocr_fixes": []} for u in units if u["kind"] == "table"]
    book_tasks = []
    for u in units:
        if u["kind"] == "task":
            m = re.match(r"^(\d+)\.\s*(.*)", u["text"], re.S)
            fig = re.search(r"рис\.?\s*\d+", u["text"])
            book_tasks.append({"number": m.group(1) if m else "", "text": (m.group(2) if m else u["text"]).strip(),
                               "figure": fig.group(0) if fig else None, "page": u["page"],
                               "ocr_bad": bool(u.get("ocr_bad"))})
    pages = sorted({p for u in units for p in u["pages"]})
    result = {
        "id": nid, "order": idx, "part_id": None, "minutes": 0,
        "title": node["title"] or _clean_title(node["book_title"])[:60], "book_title": node["book_title"],
        "pages": [pages[0], pages[-1]], "difficulty": node["difficulty"], "threshold": node["threshold"],
        "format": _route(node, pack, str(out.get("format_reason") or "")),
        "summary": P(out.get("summary")), "how_it_works": P(out.get("how_it_works")), "steps": P(out.get("steps")),
        "examples": ex_out, "numbers": P(out.get("numbers")), "formulas": formulas, "tables": tables,
        "misconception": mis, "data_meaning": dm, "analogy": an, "now_practice": P(out.get("now_practice")),
        "layers": {k: P(layers.get(k)) for k in ("mechanism", "practice", "nuances", "deeper")},
        "book_tasks": book_tasks, "illustrations": [], "links": [], "claims": claims, "term_ids": [],
        "units": node["units"], "video_criteria": node.get("video_criteria", []),
        "fallback": bool(out.get("_fallback")),
    }
    words = sum(len(p["text"].split()) for p in iter_paras(result))
    result["minutes"] = max(2, round(words / 120 + 1.5 * len(ex_out) + 0.5 * len(formulas)))
    gloss = [g for g in out.get("glossary") or [] if isinstance(g, dict) and g.get("term") and g.get("definition")]
    return result, gloss, claims


def _bad_claims(out: dict, by_id: dict) -> dict:
    bad = {}
    for c in out.get("claims") or []:
        if isinstance(c, dict):
            ok, why = check_claim(dict(c), by_id)
            if not ok:
                bad[str(c.get("id"))] = why
    return bad


# ---------------------------------------------------------------- tasks

def make_tasks(node: dict, slot: int, llm: LLM, pack: dict, log) -> tuple[list[dict], dict | None, int]:
    claims = [c for c in node["claims"] if c["verified"]] or node["claims"]
    if not claims:
        paras = list(iter_paras(node))
        back = paras[0]["text"] if paras else node["book_title"] or node["title"]
        return [], {"id": f"{node['id']}.card", "node_id": node["id"], "front": node["title"], "back": back}, slot
    text = node_plain_text(node)
    has_calc = bool(node["formulas"] or node["examples"] or len(numbers(text)) >= 2)
    want, s = [], slot
    while len(want) < (3 if len(claims) >= 4 else 2) and s < slot + 10:
        t = TASK_CYCLE[s % len(TASK_CYCLE)]
        s += 1
        if t == "calc" and not has_calc:
            continue
        if t == "order" and len(claims) < 3:
            continue
        want.append(t)
    payload = {"task": "tasks", "node": {"title": node["title"]},
               "text": [{"text": p["text"], "claims": p["claims"]} for p in iter_paras(node)],
               "claims": [{"id": c["id"], "kind": c["kind"], "text": c["text"], "quote": c["quote"]} for c in claims],
               "types": want}
    out = _ask(llm, _prompt("tasks", pack), payload, "tasks", log)
    tasks = []
    ids = {c["id"] for c in node["claims"]}
    for i, t in enumerate(out.get("tasks") or [], 1):
        if not isinstance(t, dict):
            continue
        if t.get("claim_id") not in ids:
            t["claim_id"] = claims[0]["id"]
        err = check_task(t, text)
        if err:
            log(f"  задание {node['id']}#{i} отброшено: {err}")
            continue
        t = {"id": f"{node['id']}.q{i}", "node_id": node["id"], **{k: v for k, v in t.items() if k not in ("id", "node_id")}}
        tasks.append(t)
    card = out.get("card")
    card = ({"id": f"{node['id']}.card", "node_id": node["id"], "front": str(card["front"]), "back": str(card["back"])}
            if isinstance(card, dict) and card.get("front") and card.get("back") else
            {"id": f"{node['id']}.card", "node_id": node["id"], "front": node["title"],
             "back": (node["summary"][0]["text"] if node["summary"] else claims[0]["text"])})
    return tasks, card, s


# ---------------------------------------------------------------- assemble

def build_layer(chapter_id: str, cfg: dict, units: list[dict], llm: LLM, pack: dict, log=print) -> tuple[dict, list[dict]]:
    by_id = {u["id"]: u for u in units}
    key = chapter_id.split("_", 1)[-1]
    raw_nodes, skip = outline(units, llm, pack, cfg, log)
    raw_nodes = order_nodes(split_large(raw_nodes, by_id), by_id)
    # Термины, уже объяснённые до узла, — по outline (детерминированно), чтобы узлы заполнять параллельно.
    known_before, acc = [], []
    for rn in raw_nodes:
        known_before.append(list(acc))
        acc += rn.get("new_terms", [])
    workers = llm.parallel
    with ThreadPoolExecutor(max_workers=workers) as ex:
        filled = list(ex.map(lambda a: fill_node(a[1], a[0], key, by_id, llm, pack, known_before[a[0] - 1], log),
                             enumerate(raw_nodes, 1)))
    nodes, glossary = [], []
    for i, (rn, (node, gloss, _)) in enumerate(zip(raw_nodes, filled), 1):
        node["links"] = [{"to": f"{key}.{p}", "type": "prerequisite"} for p in rn["prereqs"]]
        for g in gloss:
            tid = "t-" + (_slug(g.get("en") or "") if g.get("en") else str(len(glossary) + 1))
            if any(skeleton(x["term"]) == skeleton(g["term"]) for x in glossary):
                continue
            while any(x["id"] == tid for x in glossary):
                tid += "-x"
            glossary.append({"id": tid, "term": str(g["term"]), "en": str(g.get("en") or ""),
                             "definition": str(g["definition"]), "node_id": node["id"], "page": node["pages"][0]})
            node["term_ids"].append(tid)
        nodes.append(node)
        log(f"узел {i}/{len(raw_nodes)}: {node['title']} — утверждений {len(node['claims'])}, "
            f"проверено {sum(c['verified'] for c in node['claims'])}")
    # Части: подряд идущие узлы одного раздела книги.
    parts = []
    for n, rn in zip(nodes, raw_nodes):
        sec = by_id[rn["units"][0]]["section"] or cfg["title"]
        if not parts or parts[-1]["_sec"] != sec:
            parts.append({"_sec": sec, "id": f"p{len(parts) + 1}", "title": _clean_title(sec), "node_ids": []})
        parts[-1]["node_ids"].append(n["id"])
        n["part_id"] = parts[-1]["id"]
    for p in parts:
        p.pop("_sec")
    # Задания и карточки.
    tasks, cards = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        made = list(ex.map(lambda a: make_tasks(a[1], 2 * a[0], llm, pack, log), enumerate(nodes)))
    for t, c, _ in made:
        tasks += t
        if c:
            cards.append(c)
    # Покрытие.
    owner = {x: n["id"] for n in nodes for x in n["units"]}
    reasons = {s["unit"]: s["reason"] for s in skip}
    coverage = [{"unit": u["id"], "page": u["page"], "kind": u["kind"], "node": owner.get(u["id"]),
                 "reason": "" if u["id"] in owner else reasons.get(u["id"], ""),
                 "ocr_bad": bool(u.get("ocr_bad"))} for u in units]
    pages = sorted({u["page"] for u in units})
    layer = {
        "schema_version": "1.0",
        "chapter": {"id": key, "title": cfg["title"], "title_short": cfg.get("title_short") or cfg["title"],
                    "book": cfg["book"], "author": cfg["author"], "year": cfg["year"], "pages": [pages[0], pages[-1]],
                    "pdf": "source.pdf" if cfg.get("_pdf") else "",
                    "built_with": {"model": llm.name, "pipeline": cfg.get("_git", ""),
                                   "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}},
        "parts": parts, "nodes": nodes, "tasks": tasks, "cards": cards, "glossary": glossary,
    }
    return layer, coverage


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
