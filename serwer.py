#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serwer.py — API (FastAPI) dla narzędzia Marek_voice.

Ładuje model XTTS-v2 RAZ ("ciepły" model), dzięki czemu kolejne syntezy ruszają
bez ~15 s narzutu. Obsługuje: syntezę tekstu/pliku, listę i przełączanie profili
głosowych oraz tworzenie profilu z nagranej próbki. Serwuje też GUI z web/.

Uruchomienie:
    ./serwuj                       # lub: .venv/bin/python serwer.py
    http://127.0.0.1:8000

Zmienne środowiskowe: MOWA_PORT (domyślnie 8000), MOWA_URZADZENIE (auto/cpu/cuda/mps),
MOWA_DEEPSPEED=1 (CUDA).
"""
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import mowmoim as m

DIR = Path(__file__).parent
GLOS_DIR = DIR / "glos"
WEB_DIR = DIR / "web"
WYJSCIE_DIR = DIR / "nagrania"
GLOS_DIR.mkdir(exist_ok=True)
WYJSCIE_DIR.mkdir(exist_ok=True)

MEDIA = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
         "ogg": "audio/ogg", "flac": "audio/flac"}
TEKST_SUF = (".txt", ".docx", ".md")

# --- stan globalny: ciepły model + cache odcisków profili ---
_LOCK = threading.Lock()                 # serializuje syntezę (jeden model)
_STAN = {"model": None, "sr": 24000, "device": None}
_ODCISKI: dict[str, tuple[float, object]] = {}   # nazwa -> (mtime, odcisk)


def _zaladuj_model():
    if _STAN["model"] is None:
        device = m.wykryj_urzadzenie(os.environ.get("MOWA_URZADZENIE", "auto"))
        ds = os.environ.get("MOWA_DEEPSPEED", "") == "1"
        print(f"[serwer] Ładuję model XTTS-v2 na: {device}"
              f"{' + DeepSpeed' if ds and device == 'cuda' else ''}...")
        _STAN["device"] = device
        _STAN["model"], _STAN["sr"] = m.zaladuj_model(device, ds)
        print("[serwer] Model gotowy.")
    return _STAN["model"], _STAN["sr"]


def lista_profili() -> list[str]:
    return sorted(p.stem for p in GLOS_DIR.glob("*.wav"))


def _profil_sciezka(nazwa: str) -> Path:
    bezp = re.sub(r"[^\w\-]+", "_", nazwa).strip("_")   # sanityzacja nazwy pliku
    if not bezp:
        raise HTTPException(400, "Nieprawidłowa nazwa profilu")
    return GLOS_DIR / f"{bezp}.wav"


def _odcisk(nazwa: str):
    """Odcisk głosu profilu — cache'owany, unieważniany po zmianie pliku (mtime)."""
    sciezka = _profil_sciezka(nazwa)
    if not sciezka.exists():
        raise HTTPException(404, f"Brak profilu: {nazwa}")
    mtime = sciezka.stat().st_mtime
    cache = _ODCISKI.get(sciezka.stem)
    if not cache or cache[0] != mtime:
        model, _ = _zaladuj_model()
        _ODCISKI[sciezka.stem] = (mtime, m.policz_odcisk(model, sciezka))
    return _ODCISKI[sciezka.stem][1]


def _normalizuj_do_wav(src: Path, cel: Path, start: float = 0.0, koniec: float = 0.0) -> None:
    """Normalizacja próbki jak w przygotuj_glos.sh: 24 kHz mono, loudnorm, filtr pasma.
    Opcjonalne przycięcie: [start, koniec] w sekundach (koniec=0 → do końca nagrania)."""
    cel.parent.mkdir(parents=True, exist_ok=True)
    # -ss/-t jako opcje WYJŚCIA (po -i) → dokładne, próbka-w-próbkę przycięcie.
    trim = []
    if koniec and koniec > start >= 0:
        trim = ["-ss", f"{start:.3f}", "-t", f"{koniec - start:.3f}"]
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), *trim,
         "-af", "loudnorm=I=-18:TP=-2:LRA=11,highpass=f=70,lowpass=f=8500",
         "-ar", "24000", "-ac", "1", str(cel)],
        check=True,
    )


# Bezpieczne limity długości fragmentu wg języka (XTTS-v2 ma różne limity znaków).
LIMITY = {"pl": 200, "en": 230, "de": 230, "fr": 240, "es": 220, "it": 200, "pt": 190,
          "nl": 230, "cs": 180, "ru": 170, "tr": 210, "ar": 150, "zh-cn": 78, "ja": 66,
          "ko": 90, "hu": 200, "hi": 140}

app = FastAPI(title="Clone-my-voice — studio")


@app.get("/api/status")
def status():
    return {"gotowy": _STAN["model"] is not None,
            "urzadzenie": _STAN["device"],
            "profile": lista_profili(),
            "formaty": list(m.FORMATY)}


@app.get("/api/profile")
def get_profile():
    return {"profile": lista_profili()}


@app.post("/api/profile")
def dodaj_profil(nazwa: str = Form(...), plik: UploadFile = File(...),
                 start: float = Form(0.0), koniec: float = Form(0.0)):
    """Tworzy/aktualizuje profil głosowy z przesłanego nagrania (dowolny format audio).
    Opcjonalne przycięcie start/koniec (sekundy) — obcina ciszę/trzaski z końców."""
    cel = _profil_sciezka(nazwa)
    suf = Path(plik.filename or "x").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
        tmp.write(plik.file.read())
        tmp_path = tmp.name
    try:
        _normalizuj_do_wav(Path(tmp_path), cel, start, koniec)
    except subprocess.CalledProcessError:
        raise HTTPException(400, "Nie udało się przetworzyć nagrania (zły format audio?)")
    finally:
        os.unlink(tmp_path)
    _ODCISKI.pop(cel.stem, None)          # unieważnij cache odcisku
    return {"ok": True, "profil": cel.stem, "profile": lista_profili()}


@app.get("/api/profile/{nazwa}/audio")
def profil_audio(nazwa: str):
    """Zwraca znormalizowaną próbkę profilu (do odsłuchu/porównania w GUI)."""
    sciezka = _profil_sciezka(nazwa)
    if not sciezka.exists():
        raise HTTPException(404, f"Brak profilu: {nazwa}")
    return FileResponse(str(sciezka), media_type="audio/wav", filename=f"{sciezka.stem}.wav")


@app.delete("/api/profile/{nazwa}")
def usun_profil(nazwa: str):
    sciezka = _profil_sciezka(nazwa)
    if not sciezka.exists():
        raise HTTPException(404, f"Brak profilu: {nazwa}")
    sciezka.unlink()
    _ODCISKI.pop(sciezka.stem, None)
    return {"ok": True, "profile": lista_profili()}


@app.post("/api/mowa")
def mowa(text: str = Form(""), profil: str = Form(...), format: str = Form("mp3"),
         predkosc: float = Form(1.0), jezyk: str = Form("pl"),
         plik: UploadFile | None = File(None)):
    """Synteza: z pola `text` albo z przesłanego pliku .txt/.docx. Zwraca plik audio."""
    if format not in m.FORMATY:
        raise HTTPException(400, f"Nieobsługiwany format: {format}")
    if plik is not None and plik.filename:
        suf = Path(plik.filename).suffix.lower()
        if suf not in TEKST_SUF:
            raise HTTPException(400, f"Nieobsługiwany typ pliku: {suf} (użyj .txt/.docx)")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
            tmp.write(plik.file.read())
            tmp_path = tmp.name
        try:
            text = m.tekst_z_pliku(Path(tmp_path))
        finally:
            os.unlink(tmp_path)
    fragmenty = m.na_fragmenty((text or "").strip(), LIMITY.get(jezyk, 200))
    if not fragmenty:
        raise HTTPException(400, "Brak tekstu do syntezy")
    with _LOCK:
        model, sr = _zaladuj_model()
        odcisk = _odcisk(profil)
        audio = m.syntezuj(model, sr, fragmenty, odcisk, jezyk, predkosc)
        out = WYJSCIE_DIR / f"mowa_{int(time.time() * 1000)}.{format}"
        m.zapisz_audio(audio, sr, out, format)
    return FileResponse(str(out), media_type=MEDIA.get(format, "application/octet-stream"),
                        filename=out.name)


# GUI (statyczne pliki) — montowane na końcu, by nie przesłaniać tras /api/*
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MOWA_PORT", "8000"))
    print(f"[serwer] http://127.0.0.1:{port}  (Ctrl+C aby zatrzymać)")
    uvicorn.run(app, host="127.0.0.1", port=port)
