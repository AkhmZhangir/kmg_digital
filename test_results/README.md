# Результаты теста — команда «ЭШПОШМАКИ»

Прогон 26.11.2026, конвейер замороженный: тег `freeze-2026-11-26`. Код, промпты и доменный пакет геологии после тега не менялись. Проверить: `git diff --stat freeze-2026-11-26 HEAD -- pipeline/core pipeline/prompts pipeline/web pipeline/domain/geology pipeline/run.py`.

## Что где

| Что | Путь |
|---|---|
| Ответ модуля проверки (пакет `test_asquith`) | [`../review/test_asquith_answer.json`](../review/test_asquith_answer.json) |
| Курсы (открыть `index.html`) | `courses/<глава>/index.html` |
| Слой, задания, маршрутизация в форматах организаторов | `courses/<глава>/official/{layer,tasks,routing,coverage,illustrations,validation}.json` |
| Отчёт проверки слоя (цитаты, схемы) | `courses/<глава>/report.json` |
| Ролики | `video/razbor-slatt-delta/` (16:9), `video/shorts-basarygin-kick/` (9:16): mp4, srt, паспорт (`passport.official.json` — по `passport.schema.json`, `passport.json` — внутренний формат конвейера) |
| Журнал ручных правок с минутами | `journal/manual_edits.csv` (формат организаторов), `journal/edits.jsonl` |
| Доменный пакет «бурение» и время сборки | [`../pipeline/domain/drilling/`](../pipeline/domain/drilling/) — `pack.json`, `BUILD_TIME.md`, `TEMPLATE_COVERAGE.md` |

## Главы

| Глава | Шагов | Заданий | Цитаты подтверждены | Схемы | Ролик |
|---|---|---|---|---|---|
| test_slatt — Slatt §9.4 (двойник 3) | 8 | 22 | 100% | 5/5 | разбор 16:9, 113,8 с |
| test_asquith — Asquith (двойник 1) | 21 | 59 | 91% | 5/5 | — |
| test_dake — Dake (двойник 2) | 14 | 30 | 93% | 5/5 | — |
| test_basarygin — Басарыгин, бурение (другой домен) | 15 | 37 | 100% | 5/5 | шортс 9:16, 56,6 с |

Ручной труд по журналу: test_basarygin 21 мин, test_slatt 19, test_asquith 16 (из них 12 — ответ модуля проверки), test_dake 5. Порог ТЗ — 30 мин на главу.

Ролики встроены в курсы на узлы, которые выбрала маршрутизация конвейера: `slatt.river-dominated-delta-facies` и `basarygin.mud-volume-increase-control`.

## Модуль проверки — пакет `test_asquith`

- Ответ: [`../review/test_asquith_answer.json`](../review/test_asquith_answer.json) (копия: `review/test_asquith_answer.json` в этой папке), проверен схемой `review_output.schema.json`.
- Прогон: `py -3 run.py review --package <пакет>/package.json` → сырой ответ модуля `review/test_asquith_module_raw.json` (17 замечаний на 95 целей), отклонённые без доказательства — `review/test_asquith_module_rejected.json`.
- Ручная доводка (12 мин, в журнале): убраны 2 ложные тревоги модуля (C052 — модель сама сочла верным; C058 — цитата есть на стр. 146), добавлены 5 пропущенных: C008 (степень 1/n в формуле 7.1), S03 (Sw и Sxo перепутаны: из Rt = 20 и Rxo = 34,7 при допущениях сцены Sw = 0,25, Sxo = 0,6), F02 (нет плашки масштаба), F04 (симуляция помечена «реальные данные»), F09 (описание перепутало кривые глубокого и мелкого зонда). Итог — 20 замечаний, у каждого fix и page_pdf.
