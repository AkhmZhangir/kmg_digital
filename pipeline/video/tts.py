"""Озвучка: онлайн-голос Microsoft (edge-tts) — основной, локальный голос Windows (SAPI, Microsoft Irina) — запасной.
Наружу уходит только текст фразы сценария. Словарь произношений доменного пакета применяется к тексту для голоса."""
import asyncio
import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 24000


def ffmpeg() -> str:
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    hits = sorted(Path.home().glob("AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin/ffmpeg.exe"))
    if hits:
        return str(hits[-1])
    raise RuntimeError("ffmpeg не найден: winget install Gyan.FFmpeg")


def speakable(text: str, pron: dict) -> str:
    """Текст для голоса: аббревиатуры по словарю произношений, без формул."""
    out = text
    for k, v in pron.items():
        if k.isupper() or not k.isalpha():
            out = re.sub(rf"(?<!\w){re.escape(k)}(?!\w)", v, out)
    return out


def to_pcm(src: Path) -> np.ndarray:
    raw = subprocess.run([ffmpeg(), "-v", "error", "-i", str(src), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


async def _edge(text: str, voice: str, rate: str, mp3: Path) -> list[dict]:
    import edge_tts
    try:
        com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:
        com = edge_tts.Communicate(text, voice, rate=rate)
    words = []
    with mp3.open("wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                words.append({"text": chunk["text"], "start": chunk["offset"] / 1e7,
                              "end": (chunk["offset"] + chunk["duration"]) / 1e7, "kind": chunk["type"]})
    return words


def _sapi(text: str, voice: str, wav: Path, rate: int = 2) -> None:
    # Текст — через файл UTF-8: stdin PowerShell 5.1 читает в кодировке консоли и портит кириллицу.
    txt = wav.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8-sig")
    ps = (f"Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SelectVoice('{voice}'); $s.Rate={rate}; $s.SetOutputToWaveFile('{wav}'); "
          f"$s.Speak((Get-Content -Raw -Encoding UTF8 '{txt}')); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)
    txt.unlink(missing_ok=True)


def synth(text: str, voice: dict, pron: dict, cache: Path) -> dict:
    """Синтез одной фразы с кешем. Возвращает {pcm, words, voice, seconds}."""
    say = speakable(text, pron)
    import hashlib
    key = hashlib.sha256(json.dumps([say, voice], ensure_ascii=False).encode()).hexdigest()[:20]
    cache.mkdir(parents=True, exist_ok=True)
    meta = cache / f"{key}.json"
    if meta.is_file():
        m = json.loads(meta.read_text(encoding="utf-8"))
        return {**m, "pcm": to_pcm(cache / m["file"])}
    used, words, file, err = voice["primary"], [], None, None
    if not voice.get("force_backup"):
        import time
        for attempt in range(int(voice.get("attempts", 4))):
            try:
                mp3 = cache / f"{key}.mp3"
                words = asyncio.run(_edge(say, voice["primary"], voice.get("rate", "+0%"), mp3))
                if mp3.stat().st_size < 1000:
                    raise RuntimeError("пустой ответ онлайн-синтеза")
                file = mp3.name
                break
            except Exception as e:  # онлайн-синтез ограничивает частоту и бывает нестабилен
                err = e
                time.sleep(2 + 3 * attempt)
    if file is None:  # запасной локальный голос Windows
        print(f"  TTS: {voice['primary']} недоступен ({type(err).__name__ if err else 'принудительно'}), запасной голос {voice['backup']}")
        wav = cache / f"{key}.wav"
        _sapi(say, voice["backup"], wav, int(voice.get("backup_rate", 2)))
        used, file = voice["backup"], wav.name
    pcm = to_pcm(cache / file)
    m = {"text": text, "spoken": say, "voice": used, "file": file, "words": words, "seconds": round(len(pcm) / SR, 3)}
    if used == voice["primary"] or voice.get("force_backup"):  # неудачную попытку онлайн-голоса не кешируем
        meta.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return {**m, "pcm": pcm}


def write_wav(path: Path, pcm: np.ndarray) -> None:
    data = (np.clip(pcm, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
