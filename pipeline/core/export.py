"""Экспорт главы в ОФИЦИАЛЬНЫЕ форматы организаторов (contract/official/schemas) + проверка схемами.

Наш внутренний layer.json (contract/LAYER_FORMAT.md) остаётся для фронтенда. Отсюда в out/<глава>/official/:
  layer.json          — node.schema.json      (учебный слой)
  coverage.json       — coverage.schema.json  (каждая единица → узел или причина)
  routing.json        — routing.schema.json   (формат узла и видеоёмкость 0–2)
  tasks.json          — task.schema.json      (5 типов заданий)
  illustrations.json  — illustration.schema.json
  validation.json     — результат проверки всех файлов схемами
"""
import json
import re
from pathlib import Path

from .textnorm import skeleton
from .verify import iter_paras

HERE = Path(__file__).resolve().parent.parent
SCHEMAS = HERE.parent / "contract" / "official" / "schemas"
OFFICIAL_DOMAIN = HERE / "domain" / "geology" / "official"

SOURCE_KIND = {"para": "text", "list": "text", "example": "text", "heading": "text", "formula": "formula",
               "table": "table", "task": "task", "figure": "figure_caption", "figure_desc": "figure_description_model"}
COV_KIND = {"para": "paragraph", "list": "paragraph", "figure": "figure", "figure_desc": "figure", "formula": "formula",
            "table": "table", "example": "worked_example", "task": "task", "heading": "heading"}
FORMAT = {"short": "шортс", "long": "длинное видео", "interactive": "интерактив", "data": "практикум на данных",
          "cards": "карточки", "text": "текст"}
SCORES = {"time_change": "time", "invisible_visible": "invisible", "scale_jump": "scale",
          "counterintuitive": "counterintuitive", "cause_effect": "cause_effect"}
TASK_TYPE = {"single": "single", "multi": "multiple", "order": "order", "cloze": "gap", "calc": "calc"}
LABEL = {"схема": "схема", "симуляция": "симуляция", "реальные данные": "реальные данные", "иллюстрация ИИ": "иллюстрация ИИ"}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", s.lower()).strip("-")


def _unit_id(uid: str) -> str:
    m = re.match(r"u(\d+)-(\d+)", uid)
    return f"p{int(m.group(1)):03d}.{int(m.group(2)):02d}" if m else uid


def _field(text, by_model=True, hypothesis=False):
    f = {"text": str(text or ""), "by_model": bool(by_model)}
    if hypothesis:
        f["hypothesis"] = True
    return f


def _join(paras):
    return " ".join(p["text"] for p in paras or [])


def _raw_span(quote: str, raw: str) -> str | None:
    """Точный кусок исходного md, соответствующий цитате (сверка по «скелету» — буквы/цифры).
    Организаторы сверяют цитату с md без учёта только пробелов и регистра, поэтому отдаём текст книги как есть."""
    from difflib import SequenceMatcher
    idx, sk = [], []
    for i, ch in enumerate(raw):
        s = skeleton(ch)
        if s:
            sk.append(s)
            idx.append(i)
    raw_sk = "".join(sk)
    q = skeleton(quote)
    if not q or not raw_sk:
        return None
    pos = raw_sk.find(q)
    if pos < 0:
        m = SequenceMatcher(None, q, raw_sk, autojunk=False).find_longest_match(0, len(q), 0, len(raw_sk))
        if m.size < 0.6 * len(q):
            return None
        pos = max(0, m.b - m.a)
    end = min(len(idx) - 1, pos + len(q) - 1)
    span = raw[idx[pos]: idx[end] + 1].strip()
    return span if len(span) >= 8 else None


def _misc_ref(text: str, misc: list[dict]):
    sk = skeleton(text)
    for m in misc:
        a = skeleton(m["text"])
        if a and (a in sk or sk in a):
            return m["id"]
    return None


def export_chapter(chapter_key: str, cfg: dict, layer: dict, units: list[dict], coverage: list[dict], out: Path) -> dict:
    by_unit = {u["id"]: u for u in units}
    misc = json.loads((OFFICIAL_DOMAIN / "misconceptions.json").read_text(encoding="utf-8")) if (OFFICIAL_DOMAIN / "misconceptions.json").is_file() else []
    gloss = {g["id"]: g for g in layer.get("glossary", [])}
    titles = {n["id"]: n["title"] for n in layer["nodes"]}
    nid = {n["id"]: _slug(n["id"]) for n in layer["nodes"]}
    claim_map = {}
    nodes = []
    for n in layer["nodes"]:
        node_id = nid[n["id"]]
        claims = []
        for i, c in enumerate(n["claims"], 1):
            u = by_unit.get(c.get("unit"), {})
            q = c.get("quote") or ""
            if u.get("text") and c.get("verified"):
                q = _raw_span(q, u["text"]) or q
            if len(q) < 8:
                continue
            cid = f"{node_id}#c{len(claims) + 1}"
            claim_map[c["id"]] = cid
            claims.append({"id": cid, "text": c.get("text") or q, "kind": c.get("kind", "inference"),
                           "page_pdf": int(c.get("page") or n["pages"][0]), "page_print": None, "quote": q,
                           "source_kind": SOURCE_KIND.get(u.get("kind"), "text"), "by_model": True,
                           "needs_scan": bool(u.get("ocr_bad")) or not c.get("verified", False)})
        if not claims:  # схема требует ≥1 утверждения — берём дословный текст первой содержательной единицы
            u = next((by_unit[x] for x in n.get("units", []) if x in by_unit and by_unit[x]["kind"] in ("para", "list", "example")), None)
            if u:
                q = re.sub(r"\s+", " ", u["text"])[:240]
                claims.append({"id": f"{node_id}#c1", "text": q, "kind": "observation", "page_pdf": u["page"], "page_print": None,
                               "quote": q, "source_kind": SOURCE_KIND.get(u["kind"], "text"), "by_model": False,
                               "needs_scan": bool(u.get("ocr_bad"))})
        prereq = [titles[l["to"]] for l in n["links"] if l["type"] == "prerequisite" and l["to"] in titles]
        why = ("Опирается на шаги: " + "; ".join(prereq) + ".") if prereq else "Открывает часть: вводит понятия, на которые опираются следующие шаги."
        L = n.get("layers") or {}
        main = _join(n["summary"]) or _join(n["how_it_works"][:2])
        mechanism = _join(L.get("mechanism")) or _join(n["how_it_works"])
        practice = _join(L.get("practice")) or _join(n["steps"]) or _join(n["examples"][0]["condition"]) if n.get("examples") else _join(L.get("practice")) or _join(n["steps"])
        nuances = _join(L.get("nuances")) or _join(n["numbers"])
        dm = n.get("data_meaning") or {}
        an = n.get("analogy")
        mis = n.get("misconception")
        needs_scan = [{"page": by_unit[x]["page"], "what": "текст повреждён распознаванием — сверить по скану"}
                      for x in n.get("units", []) if x in by_unit and by_unit[x].get("ocr_bad")]
        needs_scan += [{"page": by_unit[x]["page"], "what": "рисунок: смысл держится на легенде — сверить по скану"}
                       for x in n.get("units", []) if x in by_unit and by_unit[x]["kind"] == "figure"]
        node = {
            "id": node_id, "order": n["order"], "title": n["title"], "why_here": _field(why, by_model=False),
            "difficulty": {"primary": n["difficulty"]["primary"], "secondary": n["difficulty"].get("secondary")},
            "threshold": bool(n.get("threshold")), "pages": list(range(n["pages"][0], n["pages"][1] + 1)),
            "layers": {"topic": _field(n.get("book_title") or n["title"], by_model=False), "main": _field(main),
                       "mechanism": _field(mechanism), "practice": _field(practice), "nuances": _field(nuances),
                       "deeper": [_field(p["text"]) for p in L.get("deeper") or []]},
            "claims": claims,
            "links": [{"type": "prerequisite", "target": nid.get(l["to"], _slug(l["to"]))} for l in n["links"] if l["type"] == "prerequisite"],
            "misconception": ({"ref": _misc_ref(mis["wrong"], misc), "text": mis["wrong"], "by_model": True} if mis else None),
            "data_meaning": {"from_chapter": _field(" → ".join(x for x in (dm.get("input"), dm.get("output")) if x)),
                             "breaks": _field(_join(dm.get("breaks"))),
                             "hypotheses": [_field(p["text"], hypothesis=True) for p in dm.get("hypotheses") or []]},
            "it_analogy": ({"text": an["text"], "breaks_where": an["breaks_where"], "by_model": True} if an else
                           {"text": "", "breaks_where": "", "by_model": True}),
            "now_practice": _field(_join(n["now_practice"])) if n.get("now_practice") else None,
            "inefficiency_lens": None,
            "terms_introduced": [gloss[t]["term"] for t in n.get("term_ids", []) if t in gloss],
            "needs_scan": needs_scan,
            "decision_on_data": None,
            "worked_examples": [{"page_pdf": int(e["page"]), "condition": _join(e["condition"]),
                                 "steps": [p["text"] for p in e["solution"]], "result": _join(e["result"]), "figure": e.get("figure")}
                                for e in n.get("examples", [])],
            "book_tasks": [{"number": str(b["number"]), "page_pdf": int(b["page"]), "text": b["text"], "figure": b.get("figure")}
                           for b in n.get("book_tasks", [])],
        }
        if mis and node["misconception"]["ref"]:
            node["links"].append({"type": "refutes_misconception", "target": node["misconception"]["ref"]})
        nodes.append(node)

    chapter_id = chapter_key
    files = {}
    files["layer.json"] = {"chapter": chapter_id, "source": f"books md/{cfg['md']}",
                           "pdf_pages": [str(p) for p in range(layer["chapter"]["pages"][0], layer["chapter"]["pages"][1] + 1)],
                           "generated_by": "pipeline " + layer["chapter"]["built_with"].get("pipeline", "") + " · " + layer["chapter"]["built_with"]["model"],
                           "nodes": nodes}
    rows = []
    for c in coverage:
        u = by_unit.get(c["unit"], {})
        words = re.sub(r"[#*|$\\{}_]+", " ", u.get("text", "")).split()
        rows.append({"unit_id": _unit_id(c["unit"]), "kind": COV_KIND.get(c["kind"], "paragraph"), "page_pdf": c["page"],
                     "excerpt": " ".join(words[:12]), "node_ids": [nid[c["node"]]] if c.get("node") in nid else [],
                     "reason": None if c.get("node") else (c.get("reason") or "служебный фрагмент")})
    files["coverage.json"] = {"chapter": chapter_id, "rows": rows}
    files["routing.json"] = {"chapter": chapter_id, "routes": [
        {"node_id": nid[n["id"]], "format": FORMAT.get(n["format"]["primary"], "текст"), "secondary_format": None,
         "video_scores": {v: (2 if k in (n.get("video_criteria") or []) else 0) for k, v in SCORES.items()},
         "hook_short": False, "template": n["format"].get("scene_template"), "why": n["format"]["reason"]}
        for n in layer["nodes"]]}
    tasks = []
    for t in layer.get("tasks", []):
        cid = claim_map.get(t.get("claim_id"))
        node = next(x for x in nodes if x["id"] == nid[t["node_id"]])
        cids = [cid] if cid else [node["claims"][0]["id"]]
        typ = TASK_TYPE[t["type"]]
        rec = {"id": _slug(t["id"]), "type": typ, "step_id": nid[t["node_id"]], "claim_ids": cids,
               "prompt": t.get("text") if typ == "gap" else t["question"], "explanation": t.get("explanation", ""),
               "kind": "understanding"}
        if typ in ("single", "multiple"):
            rec["options"] = [{"id": chr(97 + i), "text": o, "misconception": None} for i, o in enumerate(t["options"])]
            rec["answer"] = chr(97 + t["answer"]) if typ == "single" else [chr(97 + i) for i in t["answer"]]
        elif typ == "order":
            rec["options"] = [{"id": f"s{i + 1}", "text": o, "misconception": None} for i, o in enumerate(t["items"])]
            rec["answer"] = [f"s{i + 1}" for i in range(len(t["items"]))]
        elif typ == "gap":
            rec["answer"] = [a[0] for a in t["answers"]]
        else:
            rec["answer"] = t["answer"]
            rec["tolerance"] = t.get("tolerance")
            rec["unit"] = t.get("unit") or None
            rec["kind"] = "data"
        tasks.append(rec)
    files["tasks.json"] = {"chapter": chapter_id, "tasks": tasks}
    ills = []
    for n in layer["nodes"]:
        for il in n.get("illustrations", []):
            ills.append({"id": _slug(il["id"]), "step_id": nid[n["id"]], "node_id": nid[n["id"]], "file": il["src"],
                         "frame_class": il["class"], "origin": "code_from_model",
                         "label": LABEL.get(il.get("provenance"), "схема"), "caption": il["caption"], "alt": il["alt"],
                         "source": il.get("redrawn_from"), "claim_ids": [], "prompt": None})
    files["illustrations.json"] = {"chapter": chapter_id, "illustrations": ills}

    dest = out / "official"
    dest.mkdir(parents=True, exist_ok=True)
    for name, obj in files.items():
        (dest / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    report = validate(dest)
    (dest / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


SCHEMA_OF = {"layer.json": "node.schema.json", "coverage.json": "coverage.schema.json", "routing.json": "routing.schema.json",
             "tasks.json": "task.schema.json", "illustrations.json": "illustration.schema.json"}


def validate(folder: Path) -> dict:
    import jsonschema
    out = {}
    for f, s in SCHEMA_OF.items():
        if not (folder / f).is_file():
            continue
        schema = json.loads((SCHEMAS / s).read_text(encoding="utf-8"))
        data = json.loads((folder / f).read_text(encoding="utf-8"))
        errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
        out[f] = {"ok": not errs, "errors": [f"{'/'.join(map(str, e.path))}: {e.message[:200]}" for e in errs[:20]], "n_errors": len(errs)}
    return out
