# Чек-лист до 10:00 (заморозка) и на тест

Все команды — из `pipeline`: `cd pipeline; $env:PYTHONUTF8=1`

## Сейчас идёт (не прерывать)
- Сборка 5 глав на Qwen: лог `pipeline/out_build_rest.log` (в конце строка ALLDONE).
- Латышова на Qwen: `pipeline/out_lat_qwen2.log` (EXIT 0 = готово, курс в `out_qwen/`).
- Модуль проверки на контрольном пакете: `pipeline/out_review.log` → `out/review/ctrl_vendelshtein/answer.json`.
- Нужен SSH-туннель к Qwen: `ssh -N -L 127.0.0.1:8081:127.0.0.1:8081 shizuko@100.75.219.124` (пароль вводит человек).

## Проверить баллы модуля проверки (только после прогона)
```
py -3 ../contract/official/review/score_review.py out/review/ctrl_vendelshtein/answer.json "../../inputs/пакет_вводных/02_модуль_проверки/контрольный_пакет/key.json"
```

## Заморозка (до 10:00)
1. Дождаться ALLDONE (или остановить — недоделанное останется черновиком).
2. Положить кеш ответов модели в репо (жюри пересоберёт без ключей):
```
git add -f .cache/llm
git commit -m "Freeze: LLM cache"
```
3. Тег и пуш:
```
git tag freeze-2026-11-26
git push origin main --tags
```

## Тест (10:00): новая глава
1. Положить md главы в `books md`, добавить запись в `chapters.json` (страницы, start/end-заголовки, types).
2. `py -3 run.py all --chapter <id>` (анализ: Qwen, затем Gemini) → курс `out/<id>/index.html`, официальные файлы `out/<id>/official/`.
3. Пакет с закладками: `py -3 run.py review --package <папка>/package.json` → `out/review/<id>/answer.json`.
4. Ручные правки — только с записью: `py -3 run.py edit --chapter <id> --minutes N --what "..."`.
5. Сайт с чатом: `py -3 server.py` → http://127.0.0.1:8770/

## Видео
Код готов (`pipeline/video`), шортс по Латышовой: `py -3 run.py video --spec video/specs/shorts_caliper.json` (2–3 мин) → `out/video/shorts-caliper/`. В курс пока не встроен.
