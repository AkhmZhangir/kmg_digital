"""Модуль проверки: принимает чужой черновой пакет по главе и находит ошибки (закладки) с исправлением и страницей.

Вход (любой из форматов):
  • наш layer.json (contract/LAYER_FORMAT.md) — проверяются claims и абзацы;
  • {"items": [{"id", "text", "quote"?, "page"?, "kind"?}]} — общий формат внешнего пакета
    (утверждения, фразы сценария, описания кадров).
Выход: remarks.json — только находки с verdict=error, остальные в отчёте.

Как снижаем ложные тревоги: LLM обязан привести дословную цитату-доказательство из книги; если цитата не находится
в главе, находка отбрасывается (кроме детерминированных: чисел, которых нет в источнике).
"""
import re

from .llm import LLM
from .textnorm import numbers, quote_match, skeleton

BATCH = 8
SEVERITY_WEIGHT = {"critical": 3, "significant": 2, "minor": 1}


def normalize_package(pkg) -> list[dict]:
    if isinstance(pkg, list):
        pkg = {"items": pkg}
    items = []
    if "nodes" in pkg:  # наш формат
        for n in pkg["nodes"]:
            for c in n.get("claims") or []:
                items.append({"id": c["id"], "text": c.get("text", ""), "quote": c.get("quote"), "page": c.get("page"), "kind": "claim"})
        return items
    for i, it in enumerate(pkg.get("items") or pkg.get("claims") or [], 1):
        if isinstance(it, str):
            it = {"text": it}
        text = it.get("text") or it.get("claim") or it.get("statement") or ""
        items.append({"id": str(it.get("id") or i), "text": text, "quote": it.get("quote"),
                      "page": it.get("page"), "kind": it.get("kind") or it.get("type") or "claim"})
    return items


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[а-яёa-z]{4,}", s.lower().replace("ё", "е"))}


def retrieve(item: dict, units: list[dict], k: int = 4) -> list[dict]:
    """Фрагменты книги для проверки: страница из пакета ±1 и лучшие по пересечению слов."""
    pool = [u for u in units if u["kind"] != "figure_desc"]
    q = _words(item["text"] + " " + (item.get("quote") or ""))
    scored = []
    for u in pool:
        score = len(q & _words(u["text"])) / (1 + len(q))
        if item.get("page") and abs(int(u["page"]) - int(item["page"])) <= 1:
            score += 0.15
        scored.append((score, u))
    scored.sort(key=lambda x: -x[0])
    return [u for _, u in scored[:k]]


def deterministic(item: dict, sources: list[dict], all_units: list[dict]) -> list[str]:
    flags = []
    src = " ".join(u["text"] for u in sources)
    chapter_nums = set().union(*(numbers(u["text"]) for u in all_units))
    extra = {n for n in numbers(item["text"]) - numbers(src) if len(n) > 1 and n not in chapter_nums}
    if extra:
        flags.append("числа нет в главе: " + ", ".join(sorted(extra)))
    if item.get("quote") and not any(quote_match(item["quote"], u["text"])[0] != "none" for u in all_units):
        flags.append("цитата не найдена в главе")
    return flags


def check_package(pkg, units: list[dict], llm: LLM, pack: dict, system: str, log=print) -> dict:
    items = normalize_package(pkg)
    by_id = {u["id"]: u for u in units}
    ctx = {it["id"]: retrieve(it, units) for it in items}
    results = {}
    for b in range(0, len(items), BATCH):
        batch = items[b:b + BATCH]
        payload = {"task": "check", "misconceptions": pack["misconceptions"],
                   "items": [{"id": it["id"], "text": it["text"], "kind": it["kind"],
                              "sources": [{"unit": u["id"], "page": u["page"], "text": u["text"][:1800]} for u in ctx[it["id"]]]}
                             for it in batch]}
        out = llm.chat_json(system, payload, task="check", temperature=0.0)
        for r in out.get("results") or []:
            if isinstance(r, dict) and str(r.get("id")) in ctx:
                results[str(r["id"])] = r
        log(f"проверка: {min(b + BATCH, len(items))}/{len(items)}")
    remarks, report = [], []
    for it in items:
        r = results.get(it["id"], {"verdict": "unclear"})
        flags = deterministic(it, ctx[it["id"]], units)
        verdict = r.get("verdict", "unclear")
        evidence_ok, page = False, it.get("page")
        if verdict == "error":
            u = by_id.get(r.get("unit"))
            cands = [u] if u else ctx[it["id"]]
            for c in cands + [x for x in units if x not in cands]:
                if r.get("evidence") and quote_match(r["evidence"], c["text"])[0] != "none":
                    evidence_ok, page = True, c["page"]
                    break
        accepted = (verdict == "error" and evidence_ok) or (bool(flags) and verdict != "ok")
        row = {"id": it["id"], "text": it["text"], "verdict": verdict, "accepted": accepted, "flags": flags,
               "category": r.get("category"), "severity": r.get("severity") if r.get("severity") in SEVERITY_WEIGHT else "significant",
               "correction": r.get("correction"), "evidence": r.get("evidence"), "page": page}
        report.append(row)
        if accepted:
            remarks.append({k: row[k] for k in ("id", "category", "severity", "correction", "evidence", "page", "flags")})
    return {"remarks": remarks, "all": report,
            "summary": {"items": len(items), "flagged": len(remarks),
                        "rejected_no_evidence": sum(1 for r in report if r["verdict"] == "error" and not r["accepted"])}}


_FLIPS = [("больше", "меньше"), ("выше", "ниже"), ("увеличивается", "уменьшается"), ("возрастает", "убывает"),
          ("повышается", "понижается"), ("прямо", "обратно"), ("положительн", "отрицательн")]
_QUALIFIERS = re.compile(r"(?i)\b(обычно|как правило|часто|в большинстве случаев|в чистых [а-я]+|при [а-я]+ условиях|иногда),?\s*")


def make_synthetic(layer: dict, rate: float = 0.25, seed: int = 7) -> tuple[dict, list[dict]]:
    """Пакет с синтетическими закладками из проверенных утверждений слоя: переворот знака, сверхобобщение, число ×10."""
    import random
    rnd = random.Random(seed)
    items, key = [], []
    claims = [c for n in layer["nodes"] for c in n["claims"] if c.get("verified")]
    for c in claims:
        text, error, cat = c["text"], False, None
        if rnd.random() < rate:
            low = text.lower()
            flip = next(((a, b) for a, b in _FLIPS if a in low or b in low), None)
            nums = re.findall(r"\d+(?:[.,]\d+)?", text)
            if flip:
                a, b = flip
                text = re.sub(a, "\0", text, flags=re.I)
                text = re.sub(b, a, text, flags=re.I).replace("\0", b)
                error, cat = True, "переворот знака"
            elif _QUALIFIERS.search(text):
                text = _QUALIFIERS.sub("", text, count=1)
                text = "Всегда: " + text[0].lower() + text[1:]
                error, cat = True, "сверхобобщение"
            elif nums:
                n = nums[0]
                text = text.replace(n, str(int(float(n.replace(",", ".")) * 10)), 1)
                error, cat = True, "неверное число"
        items.append({"id": c["id"], "text": text, "page": c["page"], "kind": "claim"})
        key.append({"id": c["id"], "error": error, "category": cat, "severity": "significant"})
    return {"items": items}, key


def score(remarks: list[dict], key: list[dict]) -> dict:
    """Самопроверка по ключу: key = [{"id", "error": bool, "severity"}]. Правила ТЗ: полный балл с исправлением
    и страницей, половина без них; пометка верного — ложная тревога."""
    truth = {str(k["id"]): k for k in key}
    got = {str(r["id"]): r for r in remarks}
    total = sum(SEVERITY_WEIGHT.get(k.get("severity", "significant"), 2) for k in key if k.get("error"))
    pts, found, false_alarms = 0.0, 0, 0
    for i, r in got.items():
        k = truth.get(i)
        if not k or not k.get("error"):
            false_alarms += 1
            continue
        found += 1
        w = SEVERITY_WEIGHT.get(k.get("severity", "significant"), 2)
        pts += w if (r.get("correction") and r.get("page")) else w / 2
    n_err = sum(1 for k in key if k.get("error"))
    return {"errors_in_key": n_err, "found": found, "recall": round(found / n_err, 3) if n_err else None,
            "false_alarms": false_alarms, "points": pts, "max_points": total}
