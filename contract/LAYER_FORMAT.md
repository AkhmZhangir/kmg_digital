# Формат `layer.json` — контракт ядро ↔ фронтенд

Версия **1.0**. Ядро (Claude) пишет `layer.json`, `render.py` (Codex) из него собирает курс.
Менять формат может только Claude. Нужно поле — напиши в `CODEX_TO_CLAUDE.md`.
Рабочий пример: `contract/layer.example.json`.

Все тексты в UTF-8. Формулы — LaTeX без `$`. Все `id` стабильны между пересборками.

## Верхний уровень
```jsonc
{
  "schema_version": "1.0",
  "chapter": {
    "id": "latyshova.ch5",
    "title": "Построение разрезов скважин…",   // название из книги
    "title_short": "Как читать разрез скважины", // для новичка
    "book": "Практическое руководство по интерпретации диаграмм ГИС",
    "author": "М. Г. Латышова", "year": 1991,
    "pages": [90, 108],             // PDF-страницы
    "pdf": "source.pdf",            // путь относительно папки курса или "" если PDF нет
    "pdf_first_page": 90,           // source.pdf — ТОЛЬКО страницы главы (лимит 30 МБ). Книжная стр. N → source.pdf#page=(N − pdf_first_page + 1)
    "built_with": {"model": "qwen3.6", "pipeline": "git-sha", "built_at": "ISO-время"}
  },
  "parts":  [ Part ],
  "nodes":  [ Node ],               // в порядке прохождения (order)
  "tasks":  [ Task ],
  "cards":  [ Card ],
  "glossary": [ Term ]              // сводный по главе
}
```

## Part
```jsonc
{ "id": "p1", "title": "Что такое разрез скважины", "node_ids": ["n01","n02"] }
```

## Node (шаг курса = узел учебного слоя)
```jsonc
{
  "id": "latyshova.ch5.reservoir-saturation",  // устойчивый id
  "order": 7, "part_id": "p2", "minutes": 6,
  "title": "Почему высокое сопротивление ещё не нефть",   // 3–7 слов, для новичка
  "book_title": "§ 20. Характер насыщения коллекторов",   // как в книге
  "pages": [101, 103],
  "difficulty": {"primary": "И", "secondary": "Н"},       // М В И Ф П Пр Н Р
  "threshold": true,                                       // пороговая идея
  "format": {"primary": "interactive", "reason": "…"},    // text|short|long|interactive|data|cards
  "summary":     [Para],      // «Суть»: 2–3 фразы, первая — главное
  "how_it_works":[Para],      // все мысли автора, фразы ≤20 слов
  "steps":       [Para],      // «По шагам», если автор описывает процедуру
  "examples":    [Example],   // разбор примеров автора
  "numbers":     [Para],      // «Цифры и условия»
  "formulas":    [Formula],
  "tables":      [Table],
  "misconception": {"wrong": "…", "right": [Para]} | null,
  "data_meaning":  {"input": "…", "output": "…", "breaks": [Para], "hypotheses": [Para]} | null,
  "analogy":       {"text": "…", "breaks_where": "…"} | null,
  "now_practice":  [Para],    // «как это делается сейчас»; может быть пустым
  "layers": {                 // сворачиваемые слои
    "mechanism": [Para], "practice": [Para], "nuances": [Para], "deeper": [Para]
  },
  "book_tasks":   [BookTask],
  "illustrations":[Illustration],   // ≥1 на шаг
  "links": [ {"to": "node-id", "type": "prerequisite|example|refutes_misconception|to_data"} ],
  "claims": [Claim],                // опора всех Para этого узла
  "term_ids": ["t-kollektor"]       // новые термины шага → glossary
}
```
Пустой блок — это `[]` или `null`. Фронт его не показывает.

## Para — абзац (единица отображения)
```jsonc
{ "text": "…", "claims": ["c12","c13"], "page": 101, "by": "model" }
```
- `page` показывается как «стр. N» у **каждого** абзаца и ведёт на `pdf#page=N`.
- `by`: `"author"` — дословная цитата автора (показывать как цитату), `"model"` — пересказ моделью (обычный текст с пометкой). ТЗ требует, чтобы это было видно.
- В тексте может встречаться inline-формула `\( … \)`, её рендерить KaTeX.
- Термины размечены как `[[t-kollektor|коллектор]]`: это ссылка на глоссарий, при первом упоминании на шаге показывать определение.

## Claim — утверждение
```jsonc
{ "id": "c12", "kind": "observation|inference|assumption",
  "text": "Против пласта кривая сопротивления поднимается",
  "quote": "дословная цитата из книги", "page": 101, "unit": "u-101-04",
  "by": "model", "verified": true }
```
Фронт показывает цитату по клику или наведению на абзац, а также метку вида (наблюдение / вывод / допущение).

## Example — разобранный пример автора
```jsonc
{ "title": "Пример 54", "page": 107,
  "condition": [Para], "solution": [Para], "result": [Para], "figure": "рис. 76" }
```

## Formula
```jsonc
{ "latex": "P_п = \\rho_{нп} / \\rho_{вп}", "page": 102,
  "vars": [{"sym": "P_п", "meaning": "параметр насыщения", "unit": "—"}] }
```

## Table
```jsonc
{ "caption": "Таблица 12", "page": 99, "markdown": "| … |", "ocr_fixes": ["«0,З» → «0,3»"] }
```

## BookTask — задача из книги
```jsonc
{ "number": "100", "text": "…", "figure": "рис. 73", "page": 104 }
```

## Illustration
```jsonc
{ "id": "ill-n07-1", "class": "A|B|C|D", "src": "media/n07-1.svg",
  "alt": "…", "caption": "…",
  "provenance": "реальные данные|симуляция|схема|иллюстрация ИИ|фото",
  "redrawn_from": "рис. 74, стр. 104" | null, "source_url": "…" | null }
```
`src` — путь относительно папки курса. Ядро кладёт файл в `<out>/media/`.

## Task — задание (≥15 на главу, ≥4 типа)
Общие поля: `id`, `node_id`, `claim_id`, `type`, `question`, `explanation` (одна фраза, видна после проверки).
```jsonc
{ "type": "single", "options": ["…","…","…"], "answer": 1 }
{ "type": "multi",  "options": ["…","…","…","…"], "answer": [0, 2] }
{ "type": "order",  "items": ["первый","второй","третий"] }            // правильный порядок; фронт перемешивает
{ "type": "cloze",  "text": "Коллектором считают пласт, если \\(k_{п,эф}\\) > {{1}} %", "answers": [["1","1,0","1.0"]] }
{ "type": "calc",   "answer": 14.4, "tolerance": 0.1, "unit": "м" }
```
Ответ на каждое задание есть в тексте шага `node_id`. Фронт показывает ссылку «вернуться к шагу».

## Card
```jsonc
{ "id": "k-n07", "node_id": "…", "front": "…", "back": "…" }
```

## Term
```jsonc
{ "id": "t-kollektor", "term": "коллектор", "en": "reservoir rock", "definition": "…", "node_id": "…", "page": 92 }
```

## Служебные поля (фронту можно не показывать)
- `nodes[].units` — id единиц главы, из которых собран узел (для таблицы покрытия).
- `nodes[].video_criteria` — критерии видеоёмкости узла; `nodes[].format.scene_template` — шаблон сцены по типу трудности.
- `book_tasks[].ocr_bad: true` — текст задачи повреждён распознаванием: показать плашку «сверить по скану» и ссылку на страницу PDF.
- `claims[].verified: false` — цитата не прошла машинную проверку: показать плашку «не проверено».

## Рядом с layer.json в папке главы
`coverage.json` (единица → узел или причина), `units.json` (все единицы главы), `report.json` (метрики и замечания), `source.pdf`, `preview.html` (запасной предпросмотр ядра).
