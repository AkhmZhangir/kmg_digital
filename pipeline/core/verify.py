"""Машинная проверка учебного слоя по главе — без LLM.

1. Дословная цитата утверждения находится в указанной единице (на указанной странице).
2. Каждое число в тексте абзацев и заданий есть в исходных единицах.
3. Ссылки узлов, задания и карточки указывают на существующие объекты.
4. Задания корректны по формату; ответ на cloze есть в тексте шага.
5. Покрытие: каждая единица главы → узел или причина.
"""
import re

from .textnorm import numbers, quote_match, skeleton

PARA_FIELDS = ("summary", "how_it_works", "steps", "numbers", "now_practice")
LAYER_FIELDS = ("mechanism", "practice", "nuances", "deeper")


def iter_paras(node: dict):
    """Все абзацы узла (вместе с вложенными в примеры, заблуждение, данные, слои)."""
    for f in PARA_FIELDS:
        yield from node.get(f) or []
    for ex in node.get("examples") or []:
        for f in ("condition", "solution", "result"):
            yield from ex.get(f) or []
    if node.get("misconception"):
        yield from node["misconception"].get("right") or []
    if node.get("data_meaning"):
        for f in ("breaks", "hypotheses"):
            yield from node["data_meaning"].get(f) or []
    for f in LAYER_FIELDS:
        yield from (node.get("layers") or {}).get(f) or []


def check_claim(claim: dict, units_by_id: dict) -> tuple[bool, str]:
    u = units_by_id.get(claim.get("unit"))
    if not u:
        return False, f"нет единицы {claim.get('unit')}"
    if u["kind"] == "figure_desc":
        return False, "цитата из автоописания рисунка, а не из текста автора"
    quote = claim.get("quote") or ""
    how, share = quote_match(quote, u["text"])
    if how == "none":
        # Модель могла указать соседнюю единицу: ищем на той же странице.
        for other in units_by_id.values():
            if other["page"] == u["page"] and other["kind"] != "figure_desc" and other["id"] != u["id"]:
                if quote_match(quote, other["text"])[0] != "none":
                    claim["unit"] = other["id"]
                    return True, "единица исправлена на " + other["id"]
        return False, f"цитата не найдена в {u['id']} (совпадение {share:.0%})"
    return True, how


def para_number_issues(text: str, source_text: str, chapter_numbers: set) -> list[str]:
    missing = numbers(text) - numbers(source_text)
    return sorted(n for n in missing if n not in chapter_numbers or len(n) > 1)


def check_task(task: dict, node_text: str) -> str | None:
    t = task.get("type")
    if not str(task.get("question", "")).strip():
        return "пустой вопрос"
    if t in ("single", "multi"):
        opts = task.get("options") or []
        if len(opts) < 2 or len({skeleton(o) for o in opts}) != len(opts):
            return "варианты пусты или повторяются"
        a = task.get("answer")
        if t == "single" and not (isinstance(a, int) and 0 <= a < len(opts)):
            return "неверный индекс ответа"
        if t == "multi" and not (isinstance(a, list) and a and all(isinstance(i, int) and 0 <= i < len(opts) for i in a)
                                 and len(set(a)) == len(a) and len(a) < len(opts) + (len(opts) <= 2)):
            return "неверный набор ответов"
    elif t == "order":
        items = task.get("items") or []
        if not 3 <= len(items) <= 8 or len({skeleton(i) for i in items}) != len(items):
            return "для порядка нужно 3–8 разных пунктов"
    elif t == "cloze":
        text, answers = task.get("text") or "", task.get("answers") or []
        gaps = re.findall(r"\{\{(\d+)\}\}", text)
        if not gaps or len(gaps) != len(answers) or not all(isinstance(a, list) and a for a in answers):
            return "пропуски и ответы не совпадают"
        base = skeleton(node_text)
        if not all(any(skeleton(v) and skeleton(v) in base for v in a) for a in answers):
            return "ответа на пропуск нет в тексте шага"
    elif t == "calc":
        if not isinstance(task.get("answer"), (int, float)) or not isinstance(task.get("tolerance", 0), (int, float)):
            return "ответ расчёта не число"
        extra = numbers(task["question"]) - numbers(node_text)
        if extra:
            return "в условии числа не из текста шага: " + ", ".join(sorted(extra))
    else:
        return f"неизвестный тип {t}"
    return None


def node_plain_text(node: dict) -> str:
    parts = [p.get("text", "") for p in iter_paras(node)]
    parts += [c.get("text", "") + " " + c.get("quote", "") for c in node.get("claims") or []]
    parts += [f.get("latex", "") for f in node.get("formulas") or []]
    return "\n".join(parts)


def verify_layer(layer: dict, units: list[dict], coverage: list[dict] | None = None) -> dict:
    """Полная проверка готового слоя. Возвращает отчёт; ничего не бросает."""
    by_id = {u["id"]: u for u in units}
    chapter_nums = set().union(*(numbers(u["text"]) for u in units)) if units else set()
    node_ids = {n["id"] for n in layer["nodes"]}
    issues, stats = [], {"claims": 0, "claims_ok": 0, "paras": 0, "paras_number_issues": 0}
    for n in layer["nodes"]:
        claims = {c["id"]: c for c in n.get("claims") or []}
        for c in claims.values():
            stats["claims"] += 1
            ok, why = check_claim(c, by_id)
            c["verified"] = ok
            stats["claims_ok"] += ok
            if not ok:
                issues.append({"node_id": n["id"], "claim": c["id"], "message": why})
        for p in iter_paras(n):
            stats["paras"] += 1
            src = " ".join(by_id[claims[c]["unit"]]["text"] for c in p.get("claims") or []
                           if c in claims and claims[c].get("unit") in by_id)
            bad = para_number_issues(p.get("text", ""), src, chapter_nums)
            if bad:
                stats["paras_number_issues"] += 1
                issues.append({"node_id": n["id"], "message": "числа без опоры в цитате: " + ", ".join(bad),
                               "text": p.get("text", "")[:120]})
            for cid in p.get("claims") or []:
                if cid not in claims:
                    issues.append({"node_id": n["id"], "message": f"абзац ссылается на несуществующее утверждение {cid}"})
        for l in n.get("links") or []:
            if l["to"] not in node_ids:
                issues.append({"node_id": n["id"], "message": f"связь на несуществующий узел {l['to']}"})
    texts = {n["id"]: node_plain_text(n) for n in layer["nodes"]}
    types = {}
    for t in layer.get("tasks") or []:
        types[t["type"]] = types.get(t["type"], 0) + 1
        if t["node_id"] not in node_ids:
            issues.append({"task": t["id"], "message": "задание без узла"})
            continue
        err = check_task(t, texts[t["node_id"]])
        if err:
            issues.append({"task": t["id"], "node_id": t["node_id"], "message": err})
    cov = None
    if coverage is not None:
        linked = sum(1 for c in coverage if c.get("node"))
        reasoned = sum(1 for c in coverage if not c.get("node") and c.get("reason"))
        cov = {"units": len(coverage), "linked": linked, "skipped_with_reason": reasoned,
               "uncovered": len(coverage) - linked - reasoned}
        if cov["uncovered"]:
            issues.append({"message": f"{cov['uncovered']} единиц без узла и без причины"})
    return {
        "nodes": len(layer["nodes"]), "tasks": len(layer.get("tasks") or []), "task_types": types,
        "cards": len(layer.get("cards") or []), "coverage": cov, **stats,
        "claims_verified_share": round(stats["claims_ok"] / stats["claims"], 3) if stats["claims"] else 0,
        "requirements": {
            "tasks>=15": len(layer.get("tasks") or []) >= 15,
            "task_types>=4": len(types) >= 4,
            "cards_all_nodes": {c["node_id"] for c in layer.get("cards") or []} >= node_ids,
            "coverage_100": bool(cov) and cov["uncovered"] == 0,
        },
        "issues": issues,
    }
