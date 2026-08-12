#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mowmoim.py — zamienia tekst (.txt, .docx lub schowek) na plik audio (mp3/wav/...)
czytany Twoim sklonowanym głosem (Coqui XTTS-v2, lokalnie, offline).

Przykłady:
    python mowmoim.py wyklad.txt
    python mowmoim.py notatka.docx -f wav -o komentarz.wav
    python mowmoim.py --schowek --graj
    python mowmoim.py --tekst "Dzień dobry, tu Marek." -o powitanie.mp3
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# XTTS jest gadatliwy i wymaga zgody na licencję modelu — ustawiamy to zanim
# zaimportujemy bibliotekę, żeby nie zawiesić się na interaktywnym pytaniu.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
DOMYSLNY_GLOS = Path(__file__).parent / "glos" / "Marek_ref.wav"
MAX_ZNAKOW = 200          # bezpieczny fragment dla XTTS (limit pl = 224)
FORMATY = {
    "mp3":  ["-codec:a", "libmp3lame", "-b:a", "192k"],
    "wav":  ["-codec:a", "pcm_s16le"],
    "m4a":  ["-codec:a", "aac", "-b:a", "192k"],
    "ogg":  ["-codec:a", "libvorbis", "-qscale:a", "5"],
    "flac": ["-codec:a", "flac"],
}


# ------------------------------------------------------------------ wczytywanie
def tekst_z_pliku(sciezka: Path) -> str:
    suf = sciezka.suffix.lower()
    if suf == ".docx":
        try:
            import docx  # python-docx
        except ImportError:
            sys.exit("Brak biblioteki python-docx (pip install python-docx).")
        dokument = docx.Document(str(sciezka))
        return "\n".join(p.text for p in dokument.paragraphs)
    if suf in (".txt", ".md", ""):
        # Próbujemy popularnych kodowań polskich, gdyby plik nie był w UTF-8.
        for kod in ("utf-8", "utf-8-sig", "cp1250", "iso-8859-2"):
            try:
                return sciezka.read_text(encoding=kod)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return sciezka.read_text(encoding="utf-8", errors="replace")
    sys.exit(f"Nieobsługiwany typ pliku: {suf} (użyj .txt lub .docx).")


def tekst_ze_schowka() -> str:
    try:
        import pyperclip
    except ImportError:
        sys.exit("Brak biblioteki pyperclip (pip install pyperclip).")
    return pyperclip.paste()


def pobierz_tekst(args) -> str:
    if args.tekst:
        return args.tekst
    if args.schowek:
        return tekst_ze_schowka()
    if args.wejscie:
        sciezka = Path(args.wejscie).expanduser()
        if not sciezka.exists():
            sys.exit(f"Plik nie istnieje: {sciezka}")
        return tekst_z_pliku(sciezka)
    sys.exit("Podaj plik wejściowy, albo --schowek, albo --tekst \"...\". "
             "Zobacz: python mowmoim.py -h")


# ------------------------------------------------------------------ dzielenie
def na_fragmenty(tekst: str, limit: int = MAX_ZNAKOW) -> list[str]:
    """Dzieli tekst na fragmenty <= limit znaków, po granicach zdań."""
    tekst = re.sub(r"\s+", " ", tekst).strip()
    if not tekst:
        return []
    # Dzielimy na zdania (kropka/wykrzyknik/pytajnik/wielokropek + spacja).
    zdania = re.split(r"(?<=[.!?…])\s+", tekst)
    fragmenty, biezacy = [], ""
    for zdanie in zdania:
        # Zdanie dłuższe niż limit tniemy twardo po słowach.
        while len(zdanie) > limit:
            ciecie = zdanie.rfind(" ", 0, limit)
            ciecie = ciecie if ciecie > 0 else limit
            fragmenty.append(zdanie[:ciecie].strip())
            zdanie = zdanie[ciecie:].strip()
        if len(biezacy) + len(zdanie) + 1 <= limit:
            biezacy = f"{biezacy} {zdanie}".strip()
        else:
            if biezacy:
                fragmenty.append(biezacy)
            biezacy = zdanie
    if biezacy:
        fragmenty.append(biezacy)
    return fragmenty


# ------------------------------------------------------------------ audio
def polacz_i_konwertuj(wavy: list[Path], wyjscie: Path, fmt: str) -> None:
    """Łączy fragmenty WAV i koduje do docelowego formatu (ffmpeg)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lista:
        for w in wavy:
            lista.write(f"file '{w.as_posix()}'\n")
        lista_path = lista.name
    try:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", lista_path,
               *FORMATY[fmt], str(wyjscie)]
        subprocess.run(cmd, check=True)
    finally:
        os.unlink(lista_path)


# ------------------------------------------------------------------ main
def main() -> None:
    p = argparse.ArgumentParser(
        description="Zamień tekst na mowę Twoim sklonowanym głosem (XTTS-v2).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("wejscie", nargs="?", help="plik .txt lub .docx")
    p.add_argument("--schowek", action="store_true", help="czytaj tekst ze schowka systemowego")
    p.add_argument("--tekst", help="tekst podany bezpośrednio w cudzysłowie")
    p.add_argument("-o", "--output", help="plik wyjściowy (domyślnie obok wejścia)")
    p.add_argument("-f", "--format", choices=list(FORMATY), default="mp3", help="format audio (domyślnie mp3)")
    p.add_argument("-g", "--glos", default=str(DOMYSLNY_GLOS), help="próbka głosu referencyjnego (.wav)")
    p.add_argument("-j", "--jezyk", default="pl", help="język tekstu (domyślnie pl)")
    p.add_argument("--predkosc", type=float, default=1.0, help="tempo mowy (1.0 = normalne)")
    p.add_argument("--urzadzenie", choices=["cpu", "mps", "auto"], default="cpu",
                   help="urządzenie obliczeniowe (domyślnie cpu — najstabilniejsze na Mac)")
    p.add_argument("--graj", action="store_true", help="odtwórz wynik po wygenerowaniu (afplay)")
    args = p.parse_args()

    # 1) tekst
    tekst = pobierz_tekst(args).strip()
    if not tekst:
        sys.exit("Brak tekstu do przeczytania (źródło było puste).")
    fragmenty = na_fragmenty(tekst)
    print(f"Tekst: {len(tekst)} znaków → {len(fragmenty)} fragment(ów).")

    # 2) głos referencyjny
    glos = Path(args.glos).expanduser()
    if not glos.exists():
        sys.exit(f"Brak próbki głosu: {glos}\n(Przygotuj ją skryptem przygotuj_glos.sh.)")

    # 3) plik wyjściowy
    if args.output:
        wyjscie = Path(args.output).expanduser()
    elif args.wejscie:
        wyjscie = Path(args.wejscie).expanduser().with_suffix("." + args.format)
    else:
        wyjscie = Path.cwd() / f"mowa.{args.format}"

    # 4) model
    device = args.urzadzenie
    if device == "auto":
        try:
            import torch
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        except Exception:
            device = "cpu"
    print(f"Ładuję model XTTS-v2 na: {device} (pierwsze uruchomienie pobiera ~1.8 GB)...")
    from TTS.api import TTS  # import tutaj — biblioteka ładuje się kilka sekund
    tts = TTS(MODEL).to(device)

    # 5) synteza fragment po fragmencie
    tmpdir = Path(tempfile.mkdtemp(prefix="mowmoim_"))
    wavy = []
    try:
        for i, frag in enumerate(fragmenty, 1):
            print(f"  [{i}/{len(fragmenty)}] {frag[:60]}...")
            czesc = tmpdir / f"czesc_{i:04d}.wav"
            tts.tts_to_file(text=frag, speaker_wav=str(glos), language=args.jezyk,
                            speed=args.predkosc, file_path=str(czesc), split_sentences=False)
            wavy.append(czesc)

        # 6) sklejenie + konwersja
        print(f"Łączę i zapisuję → {wyjscie}")
        polacz_i_konwertuj(wavy, wyjscie, args.format)
    finally:
        for w in wavy:
            w.unlink(missing_ok=True)
        try:
            tmpdir.rmdir()
        except OSError:
            pass

    print(f"Gotowe: {wyjscie}")
    if args.graj and sys.platform == "darwin":
        subprocess.run(["afplay", str(wyjscie)])


if __name__ == "__main__":
    main()
