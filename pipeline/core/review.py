"""Модуль проверки по формату организаторов (contract/official/review):
вход — review_package.json (items: claim / analogy / script_line / scene_fact, frames, scenes) + md главы,
выход — review_output.json (remarks: target, category, severity, problem, fix, page_pdf, quote).

Как держим ложные тревоги низкими:
- элементы проверяются группами по узлу вместе с настоящими страницами главы;
- замечание модели принимается, только если её доказательство дословно находится в главе (для кадров и фактов сцены —
  в главе или в спецификации сцены);
- формальные правила кадров (метка происхождения ↔ класс кадра) проверяются кодом.
"""
import json
import re
from pathlib import Path

from .llm import LLM, LLMError
from .textnorm import quote_match
from .units import load_pages

CATEGORIES = {"overgeneralization", "sign_flip", "measured_vs_inferred", "lost_condition", "missing_caveat", "wrong_scaling",
              "wrong_mechanism", "outdated_as_current", "analogy_without_limit", "frame_error", "other"}
SEVERITY = {"critical", "significant", "minor"}
HERE = Path(__file__).resolve().parent.parent
PAGE_CHARS = 5000


def _page_text(pages: dict, p: int) -> str:
    t = re.sub(r"(?ms)^-{3,}\s*\n━━━.*?(?=^-{3,}\s*$|\Z)", "", pages.get(p, ""))  # без автоописаний рисунков
    return re.sub(r"\n{3,}", "\n\n", t)[:PAGE_CHARS]


def _find_page(evidence: str, pages: dict, hint: int | None) -> int | None:
    order = ([hint] if hint in pages else []) + [p for p in pages if p != hint]
    for p in order:
        if quote_match(evidence, pages[p], min_len=12)[0] != "none":
            return p
    return None


def frame_rules(frames: list[dict]) -> dict:
    """Формальные проверки кадров по ТЗ: метка ставится по тому, как кадр сделан."""
    out = {}
    for f in frames:
        cls, label = f.get("frame_class"), (f.get("label") or "").strip()
        if cls == "B" and label == "реальные данные":
            out[f["id"]] = ("frame_error", "significant",
                            "Кадр класса B (процесс, вычислен из модели) помечен как «реальные данные»: метка ставится по тому, как сделан кадр.",
                            "Метка «симуляция» (или «схема»); «реальные данные» — только для кадров класса A, построенных из реальных данных.")
        elif cls == "A" and label in ("симуляция", "иллюстрация ИИ"):
            out[f["id"]] = ("frame_error", "significant", f"Кадр класса A (данные) помечен «{label}».",
                            "Для данных — метка «реальные данные» и рендер кодом из данных.")
        elif cls in ("A", "B") and label == "иллюстрация ИИ":
            out[f["id"]] = ("frame_error", "critical", "Генеративный кадр в классе A/B запрещён.", "Перерисовать кодом из модели состояния.")
    return out


def review_package(pkg: dict, chapter_md: Path, llm: LLM, physics: list[dict] | None = None, log=print) -> dict:
    pages = load_pages(chapter_md)
    items = {i["id"]: i for i in pkg["items"]}
    claims = {i["id"]: i for i in pkg["items"] if i["type"] == "claim"}
    system = (HERE / "prompts" / "review.txt").read_text(encoding="utf-8").format()
    spec = (pkg.get("scenes") or [{}])[0].get("spec", {})
    spec_text = json.dumps(spec, ensure_ascii=False)

    groups: dict[str, list[dict]] = {}
    for i in pkg["items"]:
        key = "scene" if i["type"] == "scene_fact" else i.get("node_id") or "misc"
        groups.setdefault(key, []).append(i)
    if pkg.get("frames"):
        groups.setdefault("scene", [])
        groups["scene"] += [dict(f, type="frame") for f in pkg["frames"]]
    # большие группы режем, чтобы ответ модели не обрезался
    batches = []
    for key, its in groups.items():
        for k in range(0, len(its), 10):
            batches.append((key, its[k:k + 10]))

    results = {}
    for bi, (key, its) in enumerate(batches, 1):
        pg = set()
        for i in its:
            ref = claims.get(i.get("claim_ref")) if i.get("claim_ref") else None
            for c in [i, ref] + [claims[x] for x in claims if claims[x].get("node_id") == i.get("node_id")]:
                if c and c.get("page_pdf"):
                    pg.add(int(c["page_pdf"]))
        if key == "scene":
            pg |= {int(c["page_pdf"]) for c in claims.values() if c.get("node_id") == spec.get("node_id") and c.get("page_pdf")}
        view = []
        for i in its:
            v = {k: i.get(k) for k in ("id", "type", "text", "kind", "page_pdf", "quote", "breaks_where", "claim_ref", "on_screen",
                                       "spec_path", "frame_class", "label", "shows", "plaque", "t") if i.get(k) is not None}
            if i.get("claim_ref") in claims:
                c = claims[i["claim_ref"]]
                v["claim_ref_detail"] = {"text": c["text"], "quote": c.get("quote"), "page_pdf": c.get("page_pdf")}
            view.append(v)
        payload = {"task": "review", "pages": {str(p): _page_text(pages, p) for p in sorted(pg)[:6]}, "items": view}
        if key == "scene":
            payload["scene_spec"] = spec
            if physics:
                payload["physics_checklist"] = [p["item"] for p in physics]
        try:
            out = llm.chat_json(system, payload, temperature=0.0, task="review")
        except (LLMError, ValueError) as e:
            log(f"  проверка: группа {key} не обработана ({type(e).__name__}: {str(e)[:80]})")
            continue
        for r in out.get("results") or []:
            if isinstance(r, dict) and str(r.get("id")) in {i["id"] for i in its}:
                results[str(r["id"])] = r
        log(f"проверка: {bi}/{len(batches)} групп")

    remarks, rejected = [], []
    frm = frame_rules(pkg.get("frames") or [])
    frame_ids = {f["id"] for f in pkg.get("frames") or []}
    all_targets = list(items) + [f["id"] for f in pkg.get("frames") or []]
    for tid in all_targets:
        r = results.get(tid, {})
        base = items.get(tid, {})
        hint = base.get("page_pdf") or (claims.get(base.get("claim_ref"), {}).get("page_pdf"))
        if tid in frm:
            cat, sev, prob, fix = frm[tid]
            node_pages = sorted({c["page_pdf"] for c in claims.values() if c.get("node_id") == spec.get("node_id")})
            remarks.append({"target": tid, "category": cat, "severity": sev, "problem": prob, "fix": fix,
                            "page_pdf": node_pages[0] if node_pages else None, "quote": None, "_source": "rule"})
            continue
        if r.get("verdict") != "error":
            continue
        ev = str(r.get("evidence") or "")
        page = _find_page(ev, pages, r.get("page") if isinstance(r.get("page"), int) else hint) if ev else None
        in_spec = bool(ev) and quote_match(ev, spec_text, min_len=12)[0] != "none"
        is_scene = tid in frame_ids or base.get("type") == "scene_fact"
        if not (page or (is_scene and in_spec)):
            rejected.append({"target": tid, "why": "доказательство не найдено в главе", "model": r})
            continue
        if page is None:
            page = hint or (sorted({c["page_pdf"] for c in claims.values() if c.get("node_id") == spec.get("node_id")}) or [None])[0]
        remarks.append({"target": tid, "category": r.get("category") if r.get("category") in CATEGORIES else "other",
                        "severity": r.get("severity") if r.get("severity") in SEVERITY else "significant",
                        "problem": str(r.get("problem") or "").strip() or "Противоречит главе",
                        "fix": str(r.get("fix") or "").strip(), "page_pdf": page, "quote": ev[:300] if page and ev else None,
                        "_source": "model"})
    answer = {"package_id": pkg.get("package_id", ""), "team": "kmg_digital",
              "remarks": [{k: v for k, v in x.items() if not k.startswith("_")} for x in remarks]}
    return {"answer": answer, "rejected": rejected, "checked": len(results), "targets": len(all_targets), "model": llm.name}
