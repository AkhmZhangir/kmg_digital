"""Сборка ролика из спецификации сцены (video/specs/*.json) — ролик пересобирается из спецификации, а не из монтажа.

  py -3 run.py video --spec video/specs/shorts_caliper.json

Выход в out/video/<id>/: <id>.mp4, <id>.srt (полный текст, отключаемые субтитры), passport.json и passport.md
(карточка узла, сценарий с таймкодами, таблица источников, спецификация сцены, классы кадров, преувеличения,
вопросы, мост к данным, замеры: темп, громкость, распознавание речи, синхрон).
"""
import importlib
import json
import re
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core.verify import check_claim
from video.tts import SR, ffmpeg, synth, write_wav

HERE = Path(__file__).resolve().parent.parent
FONT = "C:/Windows/Fonts/segoeui.ttf"
FONT_B = "C:/Windows/Fonts/segoeuib.ttf"
GAP = 0.3          # пауза между фразами, с
LEAD = 0.3         # тишина в начале
HOLD_END = 1.5     # финальное состояние держится на экране


def _font(size, bold=False):
    try:
        return ImageFont.truetype(FONT_B if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def _wrap(d, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def timeline(spec, pron, cache, force_backup=False):
    voice = dict(spec["voice"], force_backup=force_backup)
    t, scenes, cues, chunks = LEAD, [], [], []
    for sc in spec["scenes"]:
        start = t
        for ln in sc["lines"]:
            r = synth(ln["text"], voice, pron, cache)
            chunks.append((t, r["pcm"]))
            cues.append({"start": t, "end": t + r["seconds"], "text": ln["text"], "voice": r["voice"],
                         "words": [dict(w, start=w["start"] + t, end=w["end"] + t) for w in r["words"]]})
            t += r["seconds"] + GAP
        t += sc.get("pause_after", 0)
        scenes.append({"id": sc["id"], "start": start, "end": t})
    scenes[-1]["end"] += HOLD_END
    total = scenes[-1]["end"]
    pcm = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for st, a in chunks:
        i = int(st * SR)
        pcm[i:i + len(a)] += a
    return scenes, cues, pcm[: int(total * SR)], total


def srt(cues, path):
    def ts(x):
        h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    out, n = [], 1
    for c in cues:
        words = c["text"].split()
        parts = [words[i:i + 9] for i in range(0, len(words), 9)]   # по 9 слов, время — пропорционально
        dur = c["end"] - c["start"]
        acc = 0
        for p in parts:
            a = c["start"] + dur * acc / len(words)
            acc += len(p)
            b = c["start"] + dur * acc / len(words)
            out.append(f"{n}\n{ts(a)} --> {ts(b)}\n{' '.join(p)}\n")
            n += 1
    path.write_text("\n".join(out), encoding="utf-8")


def loudness(path: Path) -> dict:
    r = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    p = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    return {"integrated_lufs": float(i.group(1)) if i else None, "true_peak_dbfs": float(p.group(1)) if p else None}


def asr_check(wav16: Path, script: str) -> dict:
    model_dir = HERE / ".cache" / "models" / "vosk-model-small-ru-0.22"
    if not model_dir.is_dir():
        return {"skipped": "нет модели vosk"}
    import wave
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    rec = KaldiRecognizer(Model(str(model_dir)), 16000)
    with wave.open(str(wav16), "rb") as w:
        while True:
            data = w.readframes(8000)
            if not data:
                break
            rec.AcceptWaveform(data)
    heard = json.loads(rec.FinalResult()).get("text", "")
    norm = lambda s: re.findall(r"[а-яё]+", s.lower().replace("ё", "е"))
    ref, hyp = norm(script), norm(heard)
    sm = SequenceMatcher(None, ref, hyp, autojunk=False)
    errors = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")
    wer = errors / max(1, len(ref))
    missed = [" ".join(ref[i1:i2]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op in ("replace", "delete")]
    return {"wer": round(wer, 3), "ok": wer <= 0.10, "words_ref": len(ref), "check_by_ear": missed[:20], "heard": heard[:400]}


def build(spec_path: Path, out_root: Path, log=print) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    pack = json.loads((HERE / "domain" / "geology" / "pack.json").read_text(encoding="utf-8"))
    pron = pack.get("pronunciation", {})
    out = out_root / spec["id"]
    out.mkdir(parents=True, exist_ok=True)
    cache = HERE / ".cache" / "tts"
    W, H = spec["size"]
    fps = spec.get("fps", 30)
    scene_mod = importlib.import_module(f"video.scenes.{spec.get('template', 'caliper')}")

    # 1. Озвучка; один голос на всю серию: если хоть одна фраза ушла на запасной — переозвучиваем всё запасным.
    scenes, cues, pcm, total = timeline(spec, pron, cache)
    for rnd in range(3):  # онлайн-голос отвечает через раз: повторяем только сбойные фразы (удачные уже в кеше)
        if all(c["voice"] == spec["voice"]["primary"] for c in cues):
            break
        log(f"  круг {rnd + 2}: повтор фраз, не взятых онлайн-голосом")
        time.sleep(20)
        scenes, cues, pcm, total = timeline(spec, pron, cache)
    if any(c["voice"] != spec["voice"]["primary"] for c in cues):
        log("  часть фраз озвучена запасным голосом — переозвучиваю весь ролик запасным для единого голоса")
        scenes, cues, pcm, total = timeline(spec, pron, cache, force_backup=True)
    voice_used = cues[0]["voice"]
    raw_wav = out / "voice_raw.wav"
    write_wav(raw_wav, pcm)
    log(f"  озвучка: {total:.1f} с, голос {voice_used}")

    # 2. Кадры из модели состояния → ffmpeg
    font, small = _font(64, True), _font(34)
    title_f, cap_f, tag_f = _font(40, True), _font(58, True), _font(28)
    mp4 = out / f"{spec['id']}.mp4"
    cmd = [ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", str(raw_wav), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
           "-shortest", "-movflags", "+faststart", str(mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    sc_by_id = {s["id"]: s for s in spec["scenes"]}
    n_frames = int(total * fps)
    t0 = time.monotonic()
    prev_state = {}
    for fi in range(n_frames):
        t = fi / fps
        k = next(i for i, s in enumerate(scenes) if t < s["end"] or i == len(scenes) - 1)
        sc = sc_by_id[scenes[k]["id"]]
        prev = spec["scenes"][k - 1]["state"] if k else {}
        p = (t - scenes[k]["start"]) / max(0.01, scenes[k]["end"] - scenes[k]["start"])
        state = scene_mod.interp_state(prev, sc["state"], max(0.0, min(1.0, p)))
        img = Image.new("RGB", (W, H), scene_mod.COL["bg"])
        scene_mod.draw(img, state, font, small)
        d = ImageDraw.Draw(img)
        # шапка: заголовок серии и метка происхождения кадра (по тому, как кадр сделан)
        d.text((60, 70), spec["title"], font=title_f, fill=(229, 236, 233))
        tag = f"{sc['provenance']} · класс {sc['class']}"
        d.rounded_rectangle([W - 60 - d.textlength(tag, font=tag_f) - 28, 140, W - 60, 190], radius=12, fill=(31, 42, 40))
        d.text((W - 60 - d.textlength(tag, font=tag_f) - 14, 148), tag, font=tag_f, fill=(154, 168, 163))
        if any(x in state.get("show", []) for x in ("cake", "invasion")):
            plate = "не в масштабе: корка увеличена ~20×"
            d.rounded_rectangle([60, 140, 60 + d.textlength(plate, font=tag_f) + 28, 190], radius=12, fill=(58, 46, 22))
            d.text((74, 148), plate, font=tag_f, fill=(221, 170, 76))
        # подпись-ключевые слова в безопасной зоне (не дублирует голос дословно)
        lines = _wrap(d, sc["caption"], cap_f, W - 160)
        y = 1500
        d.rounded_rectangle([50, y - 30, W - 50, y + 80 * len(lines) + 10], radius=24, fill=(0, 0, 0))
        for i, ln in enumerate(lines):
            d.text(((W - d.textlength(ln, font=cap_f)) / 2, y + i * 80), ln, font=cap_f, fill=(255, 255, 255))
        if sc["id"] == "predict":
            d.text((W / 2 - 30, 1380), "?", font=_font(120, True), fill=(82, 195, 191))
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()
    log(f"  кадры: {n_frames} за {time.monotonic() - t0:.0f} с → {mp4.name}")

    # 3. Субтитры, проверки
    srt(cues, out / f"{spec['id']}.srt")
    wav16 = out / "voice_16k.wav"
    subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", str(mp4), "-ac", "1", "-ar", "16000", str(wav16)], check=True)
    script = " ".join(c["text"] for c in cues)
    asr = asr_check(wav16, script)
    loud = loudness(mp4)
    words = len(script.split())
    speech = sum(c["end"] - c["start"] for c in cues)
    units = {u["id"]: u for u in json.loads((HERE / "out" / spec["chapter"] / "units.json").read_text(encoding="utf-8"))}
    sources = []
    for sc, s in zip(spec["scenes"], scenes):
        for ln, c in zip(sc["lines"], [c for c in cues if s["start"] <= c["start"] < s["end"]]):
            for cl in ln["claims"] or [{}]:
                ok = check_claim(dict(cl), units)[0] if cl else None
                sources.append({"time": round(c["start"], 2), "line": ln["text"], "page": cl.get("page"), "unit": cl.get("unit"),
                                "quote": cl.get("quote"), "verified": ok})
    fmt = spec["format"]
    lim = (40, 90) if fmt == "shorts" else (90, 180)
    checks = {
        "duration_s": round(total, 1), "duration_ok": lim[0] <= total <= lim[1],
        "hook_within_3s": cues[0]["start"] <= 0.5 and spec["scenes"][0]["id"] == "hook",
        "words_per_minute": round(words / speech * 60), "wpm_ok": 110 <= words / speech * 60 <= 150,
        "max_words_in_line": max(len(c["text"].split()) for c in cues), "line_le_18_words": all(len(c["text"].split()) <= 18 for c in cues),
        "captions_le_8_words": all(len(s["caption"].split()) <= 8 for s in spec["scenes"]),
        "captions_ge_1_5s": all(s["end"] - s["start"] >= 1.5 for s in scenes),
        "prediction_pause": any(s.get("pause_after", 0) >= 1.0 for s in spec["scenes"]),
        "sync_offset_s": 0.0, "sync_note": "сцена начинается с первой фразы, кадр и голос из одной временной шкалы",
        "loudness": loud, "loudness_ok": loud["integrated_lufs"] is not None and abs(loud["integrated_lufs"] + 16) <= 1.0,
        "asr": asr, "voice": voice_used,
        "sources_verified": sum(1 for s in sources if s["verified"]), "sources_total": sum(1 for s in sources if s["verified"] is not None),
    }
    passport = {
        "id": spec["id"], "format": fmt, "size": spec["size"], "title": spec["title"], "node_id": spec["node_id"],
        "chapter": spec["chapter"], "script": [{"start": round(c["start"], 2), "end": round(c["end"], 2), "text": c["text"]} for c in cues],
        "scenes": [{"id": s["id"], "start": round(s["start"], 2), "end": round(s["end"], 2), "class": sc["class"],
                    "provenance": sc["provenance"], "caption": sc["caption"]} for s, sc in zip(scenes, spec["scenes"])],
        "sources": sources, "scene_model": spec["scene_model"], "exaggerations": spec["scene_model"]["exaggerations"],
        "prediction_question": spec["prediction_question"], "transfer_question": spec["transfer_question"],
        "data_bridge": spec["data_bridge"], "style": spec.get("style_school"), "checks": checks,
        "tools": {"frames": "Python + Pillow (кадры A/B кодом из модели состояния, без генерации)", "voice": voice_used,
                  "tts_external": "наружу уходит только текст сценария" if "Neural" in voice_used else "локальный голос Windows, ничего не уходит наружу",
                  "assembly": "ffmpeg (libx264, AAC, loudnorm −16 LUFS)", "asr": "vosk-model-small-ru-0.22 (локально)"},
    }
    (out / "passport.json").write_text(json.dumps(passport, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "passport.md").write_text(passport_md(passport), encoding="utf-8")
    for tmp in (raw_wav, wav16):
        tmp.unlink(missing_ok=True)
    log(f"  проверки: {json.dumps({k: v for k, v in checks.items() if k not in ('asr', 'loudness')}, ensure_ascii=False)}")
    log(f"  громкость {loud}, распознавание WER {asr.get('wer')}")
    attach(spec, out, log)
    return passport


def attach(spec: dict, vdir: Path, log=print) -> None:
    """Вставляет ролик в курс главы: media/<id>.mp4 + .vtt + паспорт, поле nodes[].videos, пересборка курса."""
    import shutil
    course = HERE / "out" / spec["chapter"]
    layer_path = course / "layer.json"
    if not layer_path.is_file():
        log(f"  курс {spec['chapter']} не собран — ролик не вставлен")
        return
    media = course / "media"
    media.mkdir(exist_ok=True)
    vid = spec["id"]
    shutil.copy2(vdir / f"{vid}.mp4", media / f"{vid}.mp4")
    srt_text = (vdir / f"{vid}.srt").read_text(encoding="utf-8")
    vtt = "WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", srt_text)
    (media / f"{vid}.vtt").write_text(vtt, encoding="utf-8")
    shutil.copy2(vdir / "passport.md", media / f"{vid}.passport.md")
    layer = json.loads(layer_path.read_text(encoding="utf-8"))
    node = next((n for n in layer["nodes"] if n["id"] == spec["node_id"]), None)
    if node is None:
        log(f"  узел {spec['node_id']} не найден в курсе — ролик не вставлен")
        return
    entry = {"src": f"media/{vid}.mp4", "captions": f"media/{vid}.vtt", "title": spec["title"],
             "format": spec["format"], "passport": f"media/{vid}.passport.md"}
    node["videos"] = [v for v in node.get("videos", []) if v.get("src") != entry["src"]] + [entry]
    layer_path.write_text(json.dumps(layer, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        import render as front
        front.render(layer, course)
    except ImportError:
        pass
    log(f"  ролик вставлен в курс: {course / 'index.html'} → шаг «{node['title']}»")


def passport_md(p: dict) -> str:
    L = [f"# Паспорт ролика «{p['title']}»", "", f"Формат: {p['format']} {p['size'][0]}×{p['size'][1]} · узел `{p['node_id']}` · глава `{p['chapter']}`", "",
         "## Сценарий с таймкодами", ""]
    L += [f"- `{s['start']:6.2f}–{s['end']:6.2f}` {s['text']}" for s in p["script"]]
    L += ["", "## Таблица источников (утверждение → страница)", "", "| Время | Фраза | Стр. | Цитата | Проверено |", "|---|---|---|---|---|"]
    L += [f"| {s['time']} | {s['line']} | {s['page'] or '—'} | {(s['quote'] or '—')[:90]} | {'да' if s['verified'] else ('—' if s['verified'] is None else 'НЕТ')} |" for s in p["sources"]]
    L += ["", "## Сцены и классы кадров", "", "| Сцена | Время | Класс | Происхождение | Подпись |", "|---|---|---|---|---|"]
    L += [f"| {s['id']} | {s['start']}–{s['end']} | {s['class']} | {s['provenance']} | {s['caption']} |" for s in p["scenes"]]
    m = p["scene_model"]
    L += ["", "## Спецификация сцены", "", "**Объекты:** " + "; ".join(m["objects"]), "",
          "**Параметры:** " + "; ".join(f"{k} — {v}" for k, v in m["parameters"].items()), "",
          "**Инварианты:**", *[f"- {x}" for x in m["invariants"]], "", "**Допущения:**", *[f"- {x}" for x in m["assumptions"]], "",
          "## Преувеличения", *[f"- {x}" for x in p["exaggerations"]], "",
          f"**Вопрос-предсказание:** {p['prediction_question']}", "", f"**Вопрос на перенос:** {p['transfer_question']}", "",
          f"**Мост «где здесь данные и ИТ»:** {p['data_bridge']}", "", "## Замеры", "", "```json", json.dumps(p["checks"], ensure_ascii=False, indent=1), "```", "",
          "## Инструменты", *[f"- {k}: {v}" for k, v in p["tools"].items()]]
    return "\n".join(L) + "\n"
