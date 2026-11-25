"""Сборка учебного слоя и автономного курса по диапазону PDF-страниц."""
import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

from prepare import load_source

HERE = Path(__file__).resolve().parent
ANNOTATION = re.compile(r"(?ms)^-{3,}[ \t]*\n+^━━━.*?(?:^-{3,}[ \t]*$|\Z)")
NUM = re.compile(r"\d+(?:[.,]\d+)?")


def save(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def units_for(page, book):
    body = page["ocr"]
    spans = []
    pos = 0
    for m in ANNOTATION.finditer(body):
        spans.extend(("source", s) for s in re.split(r"\n\s*\n", body[pos:m.start()]))
        spans.append(("описание иллюстрации OCR", m.group()))
        pos = m.end()
    spans.extend(("source", s) for s in re.split(r"\n\s*\n", body[pos:]))
    result = []
    for kind, s in spans:
        s = s.strip()
        if not s:
            continue
        if kind == "source":
            kind = next((k for pattern,k in [
                (r"^#", "заголовок"), (r"^\|", "таблица"), (r"^\$\$", "формула"),
                (r"^Рис\.?", "рисунок"), (r"^Пример\s+\d", "пример"),
                (r"^\d+\.\s", "нумерованный пункт")] if re.match(pattern,s)), "текст")
        result.append(dict(id=f"{book}-p{page['pdf_page']}-u{len(result)+1}",kind=kind,text=s))
    return result


def excerpt_node(units, page):
    claims = [dict(unit=u["id"],quote=u["text"],text=u["text"]) for u in units]
    heading = next((u["text"].strip("# *") for u in units if u["kind"]=="заголовок" and len(u["text"])>13), "")
    sentences = [s.strip() for u in units if u["kind"] in ("текст","пример","нумерованный пункт")
                 for s in re.split(r"(?<=[.!?])\s+",u["text"]) if 55 <= len(s.strip()) <= 320 and not re.search(r"[|$\\]",s)]
    card = quiz = None
    if sentences:
        sentence = sentences[0]
        words = re.findall(r"[^\W\d_]{6,}",sentence)
        if words:
            answer = max(words,key=len)
            question = sentence.replace(answer,"____",1)
            unit = next(c["unit"] for c in claims if sentence in c["text"])
            quiz = dict(question=question, answer=answer, unit=unit, why=sentence)
            card = dict(front=question,back=sentence)
    title = heading or (sentences[0] if sentences else f"Материал страницы {page}")
    return dict(title=title, claims=claims,quiz=quiz,card=card)


def model_node(units, args, previous_titles, correction=""):
    payload = dict(model=args.model, messages=[
        dict(role="system",content=(HERE/"prompt.txt").read_text()),
        dict(role="user",content=json.dumps({"units": units, "previous_steps": previous_titles[-4:], "correction": correction},ensure_ascii=False))],
        response_format={"type":"json_object"})
    headers={"Content-Type":"application/json"}
    if os.getenv("LLM_API_KEY"):
        headers["Authorization"]="Bearer "+os.environ["LLM_API_KEY"]
    req=Request(args.endpoint,data=json.dumps(payload).encode(),headers=headers)
    with urlopen(req,timeout=180) as response:
        result=json.load(response)
    return json.loads(result["choices"][0]["message"]["content"]),result.get("usage",{})


def validate(node, units):
    sources={u["id"]:u["text"] for u in units}
    if not node["title"].strip() or not node["claims"]:
        raise ValueError("Пустой узел")
    for c in node["claims"]:
        if not c["text"].strip() or not c["quote"].strip() or c["quote"] not in sources.get(c["unit"], ""):
            raise ValueError("Цитата отсутствует в исходной единице: "+c["unit"])
        if set(NUM.findall(c["text"])) - set(NUM.findall(sources[c["unit"]])):
            raise ValueError("В объяснении появилось новое число: "+c["unit"])
    q=node["quiz"]
    if q:
        if q["unit"] not in {c["unit"] for c in node["claims"]} or not q["question"].strip() or not q["why"].strip():
            raise ValueError("Задание без основания")
        if "options" in q and (not isinstance(q["options"],list) or len(set(q["options"]))!=len(q["options"]) or len(q["options"])<2 or type(q["answer"]) is not int or not 0<=q["answer"]<len(q["options"])):
            raise ValueError("Неверный ключ задания")
    if node["card"] and not all(node["card"][k].strip() for k in ("front","back")):
        raise ValueError("Пустая карточка")


def generate_node(group, args, previous_titles, usage):
    correction = ""
    for _ in range(2):
        try:
            node, billing = model_node(group, args, previous_titles, correction)
            usage.append(billing)
            if not node.get("quiz") or not node.get("card"):
                raise ValueError("Пропущено задание или карточка")
            validate(node, group)
            return node
        except (ValueError, AttributeError, IndexError, KeyError, TypeError) as error:
            correction = str(error)[:300]
    raise ValueError(f"Ответ модели не прошёл проверку после повтора: {correction}")


def render(layer, out):
    content=json.dumps(layer,ensure_ascii=False).replace("<","\\u003c")
    (out/"index.html").write_text((HERE/"course.html").read_text().replace("__COURSE_JSON__",content))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("book",type=Path)
    p.add_argument("ranges", help="Например 9-14,20-30. Пустая строка выбирает весь документ.")
    p.add_argument("--ocr", action="store_true", help="Распознать выбранные PDF-страницы")
    p.add_argument("out",type=Path)
    p.add_argument("--pdf",type=Path)
    p.add_argument("--title")
    p.add_argument("--endpoint",help="Полный URL совместимого chat/completions")
    p.add_argument("--model")
    p.add_argument("--responses",type=Path,help="JSON со структурированными ответами по ID узла")
    a=p.parse_args()
    if a.responses and a.endpoint: p.error("Выберите один источник ответов")
    if bool(a.endpoint) != bool(a.model):
        p.error("--model и --endpoint указываются вместе")
    if a.pdf and not a.pdf.is_file():
        p.error("PDF не найден")
    build(a)


def build(a, source_link=None, progress=None):
    responses = json.loads(a.responses.read_text()) if a.responses else {}
    start = time.monotonic()
    pages, source_label = load_source(a.book, a.ranges, getattr(a, "ocr", False))
    original = a.pdf or (a.book if a.book.suffix.lower() == ".pdf" else None)
    layer = dict(
        title=a.title or a.book.stem,
        mode=(a.model or "Сохранённый ответ модели") if (a.model or a.responses) else "Черновик · извлечение текста",
        pdf=source_link if source_link is not None else (original.resolve().as_uri() if original else ""),
        source_label=source_label,
        ocr=bool(getattr(a, "ocr", False)),
        id=hashlib.sha256(json.dumps([a.title or a.book.stem, a.model, pages], ensure_ascii=False).encode()).hexdigest()[:20],
        nodes=[],
    )
    coverage=[]
    usage=[]
    for count, (number, page) in enumerate(sorted(pages.items()), 1):
        if progress:
            progress(count, len(pages))
        units=units_for(page,a.book.stem)
        included=[u for u in units if u["kind"]!="описание иллюстрации OCR"]
        groups=[[]]
        size=0
        for u in included:
            if size and size+len(u["text"])>6500:
                groups.append([])
                size=0
            groups[-1].append(u)
            size+=len(u["text"])
        refs={}
        if not units:
            coverage.append(dict(unit=f"{a.book.stem}-p{number}", page=number, kind="страница", node=None, reason="Нет распознанного текста"))
        for index,group in enumerate(groups,1):
            if not group: continue
            node_id=f"{a.book.stem}-p{number}-{index}"
            if a.responses:
                node=responses[node_id]
            elif a.model:
                node = generate_node(group, a, [item["title"] for item in layer["nodes"]], usage)
            else: node=excerpt_node(group,number)
            validate(node,group)
            node.update(id=node_id,page=number)
            node["format"]="практикум" if any(u["kind"] in ("пример","нумерованный пункт","таблица","формула") for u in group) else "чтение"
            for c in node["claims"]: refs[c["unit"]]=node["id"]
            layer["nodes"].append(node)
        for u in units:
            reason="" if u["id"] in refs else ("Сверить описание с рисунком в PDF" if u not in included else "Модель пропустила фрагмент")
            coverage.append(dict(unit=u["id"],page=number,kind=u["kind"],node=refs.get(u["id"]),reason=reason))
    if not layer["nodes"]: raise ValueError("Нет исходного текста")
    a.out.mkdir(parents=True, exist_ok=True)
    save(a.out/"layer.json",layer)
    save(a.out/"coverage.json",coverage)
    render(layer,a.out)
    metrics=dict(pages=len(pages),nodes=len(layer["nodes"]),units=len(coverage),linked=sum(bool(x["node"]) for x in coverage),quizzes=sum(bool(n["quiz"]) for n in layer["nodes"]),seconds=round(time.monotonic()-start,2),model=a.model,usage=usage)
    save(a.out/"report.json",metrics)
    print(a.book.stem,{k:v for k,v in metrics.items() if k!="usage"})
    return metrics


if __name__=="__main__":
    main()
