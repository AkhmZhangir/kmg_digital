"""Офлайн-заглушка LLM: детерминированные ответы из самих единиц главы.
Нужна для тестов и проверки конвейера целиком без модели. Качество — уровень «выдержки из книги»."""
import re

from .textnorm import numbers

TYPES_CYCLE = ["И", "Пр", "Н", "Ф", "М", "Р", "В", "П"]


def _sentences(text: str):
    flat = re.sub(r"\s+", " ", text)
    for s in re.split(r"(?<=[.!?])\s+(?=[А-ЯA-Z])", flat):
        s = s.strip()
        if 25 <= len(s) <= 280 and not re.search(r"[|]|\$\$|━", s):
            yield s


def respond(task: str, payload: dict) -> dict:
    if task == "fix-quotes":
        return {"claims": []}
    if task == "tutor":
        return _tutor(payload)
    return {"outline": _outline, "node": _node, "tasks": _tasks, "check": _check, "review": _review}[task.split("-")[0]](payload)


def _tutor(p):
    ctx = p["context"][:2]
    text = " ".join(c["text"] for c in ctx)
    return {"answer": "[mock] По источнику: " + text[:300],
            "citations": [{"ref": c["id"], "quote": c["text"][:120]} for c in ctx],
            "insufficient": False,
            "task": {"question": "[mock] Перескажи: " + ctx[0]["text"][:80], "answer": ctx[0]["text"][:120],
                     "ref": ctx[0]["id"]} if p["mode"] == "practice" else None,
            "followups": ["Что дальше?"]}


def _check(p):
    return {"results": [{"id": it["id"], "verdict": "unclear"} for it in p["items"]]}


def _outline(p):
    nodes, skip, cur = [], [], None
    types = p.get("chapter_types") or TYPES_CYCLE
    for u in p["units"]:
        if u["kind"] == "heading":
            skip.append({"unit": u["id"], "reason": "заголовок"})
            continue
        sec = u.get("section") or "Введение"
        if cur is None or cur["_sec"] != sec or len(cur["units"]) >= 8:
            n = len(nodes)
            cur = {"_sec": sec, "key": f"part{p.get('chunk', 0)}-{n + 1}", "title": sec[:60].capitalize(),
                   "book_title": sec, "units": [], "difficulty": {"primary": types[n % len(types)], "secondary": None},
                   "threshold": n == 0, "prereq_keys": [nodes[-1]["key"]] if nodes else [], "new_terms": [],
                   "video_criteria": ["cause_effect"] if n % 3 == 0 else []}
            nodes.append(cur)
        cur["units"].append(u["id"])
    for n in nodes:
        n.pop("_sec")
    return {"nodes": nodes, "skip": skip}


def _node(p):
    claims, paras = [], []
    for u in p["units"]:
        if u["kind"] in ("para", "list", "example", "task"):
            for s in list(_sentences(u["text"]))[:3]:
                cid = f"c{len(claims) + 1}"
                claims.append({"id": cid, "kind": "observation", "text": s, "quote": s, "unit": u["id"]})
                paras.append({"text": s, "claims": [cid]})
    formulas = [{"unit": u["id"], "latex": u["text"].strip("$ \n"), "vars": []} for u in p["units"] if u["kind"] == "formula"][:4]
    examples = []
    for u in p["units"]:
        if u["kind"] == "example":
            ex_claims = [c["id"] for c in claims if c["unit"] == u["id"]]
            if ex_claims:
                examples.append({"title": u["text"][:40], "unit": u["id"], "figure": None,
                                 "condition": [{"text": claims[int(ex_claims[0][1:]) - 1]["text"], "claims": ex_claims[:1]}],
                                 "solution": [], "result": []})
    nums = [pp for pp in paras if numbers(pp["text"])][:3]
    return {"summary": paras[:2], "how_it_works": paras[2:], "steps": [], "examples": examples, "numbers": nums,
            "formulas": formulas, "misconception": None, "data_meaning": None, "analogy": None, "now_practice": [],
            "layers": {"mechanism": [], "practice": [], "nuances": [], "deeper": []}, "glossary": [],
            "format_reason": "заглушка mock", "claims": claims}


def _tasks(p):
    claims = p["claims"]
    out = []
    if not claims:
        return {"tasks": [], "card": None}
    main = claims[0]
    others = [c["text"] for c in claims[1:]] or ["Утверждение не из этого шага."]
    for t in p["types"]:
        if t == "single":
            out.append({"type": "single", "claim_id": main["id"], "question": "Какое утверждение есть в тексте шага?",
                        "options": [main["text"], "В главе об этом говорится обратное.", "Глава этого не обсуждает."],
                        "answer": 0, "explanation": "Это утверждение приведено в тексте шага."})
        elif t == "cloze":
            words = re.findall(r"[А-Яа-яЁё]{7,}", main["text"])
            if words:
                w = max(words, key=len)
                out.append({"type": "cloze", "claim_id": main["id"], "question": "Заполните пропуск",
                            "text": main["text"].replace(w, "{{1}}", 1), "answers": [[w]],
                            "explanation": "Слово взято из текста шага."})
        elif t == "order" and len(claims) >= 3:
            out.append({"type": "order", "claim_id": main["id"], "question": "Расставьте мысли в порядке, как в тексте шага",
                        "items": [c["text"][:120] for c in claims[:3]], "explanation": "Так их излагает автор."})
        elif t == "multi" and len(claims) >= 2:
            out.append({"type": "multi", "claim_id": main["id"], "question": "Какие утверждения есть в тексте шага?",
                        "options": [main["text"][:120], others[0][:120], "Глава этого не обсуждает."],
                        "answer": [0, 1], "explanation": "Оба утверждения приведены в тексте."})
        elif t == "calc":
            nums = sorted(numbers(" ".join(c["text"] for c in claims)), key=len)
            if nums:
                out.append({"type": "calc", "claim_id": main["id"], "question": f"Какое число приводит автор в этом шаге? (одно из {', '.join(nums[:3])})",
                            "answer": float(nums[0]), "tolerance": 0, "unit": "", "explanation": "Число из текста шага."})
    return {"tasks": out, "card": {"front": p["node"]["title"], "back": main["text"]}}


def _review(p):
    return {"results": [{"id": it["id"], "verdict": "ok"} for it in p["items"]]}
