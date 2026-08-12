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
import shutil
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


ROZSZERZENIA = (".txt", ".docx", ".md")


def zbierz_pliki(wejscia: list[str]) -> list[Path]:
    """Rozwija listę ścieżek: pliki bierze wprost, foldery skanuje po .txt/.docx.
    Zwraca posortowaną listę istniejących plików wejściowych."""
    pliki: list[Path] = []
    for w in wejscia:
        p = Path(w).expanduser()
        if p.is_dir():
            pliki += sorted(f for f in p.iterdir() if f.suffix.lower() in ROZSZERZENIA)
        elif p.exists():
            pliki.append(p)
        else:
            print(f"  Pomijam (nie istnieje): {p}")
    return pliki


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


# ------------------------------------------------------------------ silnik TTS
def wykryj_urzadzenie(wybor: str) -> str:
    """auto → 'cuda' jeśli dostępne, inaczej 'cpu'.
    Na Apple Silicon celowo NIE wybieramy mps — dla XTTS jest wolniejszy niż cpu."""
    if wybor != "auto":
        return wybor
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def zaladuj_model(device: str, use_deepspeed: bool):
    """Ładuje XTTS-v2 niskopoziomowo — przenośnie (CPU/CUDA/MPS), z opcją DeepSpeed.
    Zwraca (model, sample_rate). DeepSpeed działa tylko na CUDA; w razie braku
    pakietu cichy fallback do zwykłego ładowania."""
    from TTS.utils.manage import ModelManager
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts

    model_dir, config_path, _ = ModelManager().download_model(MODEL)
    config = XttsConfig()
    config.load_json(str(config_path or Path(model_dir) / "config.json"))
    model = Xtts.init_from_config(config)

    ds = bool(use_deepspeed and device == "cuda")
    try:
        model.load_checkpoint(config, checkpoint_dir=str(model_dir), use_deepspeed=ds, eval=True)
    except Exception as e:
        if ds:
            print(f"  Uwaga: DeepSpeed niedostępny ({e}); ładuję bez DeepSpeed.")
            model.load_checkpoint(config, checkpoint_dir=str(model_dir), use_deepspeed=False, eval=True)
        else:
            raise

    if device == "cuda":
        model.cuda()
    elif device == "mps":
        model.to("mps")
    sr = int(getattr(config.audio, "output_sample_rate", 24000))
    return model, sr


def policz_odcisk(model, glos: Path):
    """Liczy 'odcisk głosu' (speaker latents) — RAZ na głos, reużywalny dla
    wszystkich fragmentów i (w trybie wsadowym) wszystkich plików."""
    return model.get_conditioning_latents(audio_path=[str(glos)])


def syntezuj(model, sr: int, fragmenty: list[str], odcisk, jezyk: str, predkosc: float):
    """Zamienia listę fragmentów tekstu na jeden sygnał audio (numpy float32),
    używając wcześniej policzonego odcisku głosu."""
    import numpy as np
    gpt_cond_latent, speaker_embedding = odcisk
    cisza = np.zeros(int(sr * 0.15), dtype=np.float32)   # krótka pauza między fragmentami
    kawalki = []
    for i, frag in enumerate(fragmenty, 1):
        print(f"    [{i}/{len(fragmenty)}] {frag[:55]}...")
        out = model.inference(frag, jezyk, gpt_cond_latent, speaker_embedding,
                              speed=predkosc, enable_text_splitting=False)
        kawalki.append(np.asarray(out["wav"], dtype=np.float32))
        if i < len(fragmenty):
            kawalki.append(cisza)
    return np.concatenate(kawalki)


def zapisz_audio(audio, sr: int, wyjscie: Path, fmt: str) -> None:
    """Zapisuje sygnał audio do pliku w docelowym formacie (przez ffmpeg)."""
    import soundfile as sf
    wyjscie.parent.mkdir(parents=True, exist_ok=True)
    tmp_wav = Path(tempfile.mktemp(suffix=".wav"))
    sf.write(str(tmp_wav), audio, sr)
    try:
        polacz_i_konwertuj([tmp_wav], wyjscie, fmt)
    finally:
        tmp_wav.unlink(missing_ok=True)


def odtworz(sciezka: Path) -> None:
    """Odtwarza plik — przenośnie: afplay (mac), ffplay/aplay/paplay (Linux)."""
    if sys.platform == "darwin":
        subprocess.run(["afplay", str(sciezka)])
        return
    for gracz in (["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["aplay"], ["paplay"]):
        if shutil.which(gracz[0]):
            subprocess.run(gracz + [str(sciezka)])
            return
    print("(Brak odtwarzacza audio — pomijam --graj)")


# ------------------------------------------------------------------ main
def main() -> None:
    p = argparse.ArgumentParser(
        description="Zamień tekst na mowę Twoim sklonowanym głosem (XTTS-v2).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("wejscie", nargs="*", help="plik(i) .txt/.docx lub folder(y) — można podać wiele (tryb wsadowy)")
    p.add_argument("--schowek", action="store_true", help="czytaj tekst ze schowka systemowego")
    p.add_argument("--tekst", help="tekst podany bezpośrednio w cudzysłowie")
    p.add_argument("-o", "--output", help="plik wyjściowy (tylko pojedyncze wejście)")
    p.add_argument("-d", "--katalog-wy", dest="katalog_wy",
                   help="katalog na wyniki (tryb wsadowy; domyślnie obok każdego wejścia)")
    p.add_argument("-f", "--format", choices=list(FORMATY), default="mp3", help="format audio (domyślnie mp3)")
    p.add_argument("-g", "--glos", default=str(DOMYSLNY_GLOS), help="próbka głosu referencyjnego (.wav)")
    p.add_argument("-j", "--jezyk", default="pl", help="język tekstu (domyślnie pl)")
    p.add_argument("--predkosc", type=float, default=1.0, help="tempo mowy (1.0 = normalne)")
    p.add_argument("--urzadzenie", choices=["auto", "cpu", "cuda", "mps"], default="auto",
                   help="urządzenie: auto (cuda→cpu), cpu, cuda (Linux/NVIDIA), mps (Mac, wolniejszy)")
    p.add_argument("--deepspeed", action="store_true",
                   help="użyj DeepSpeed — tylko CUDA/Linux, ~2x szybciej (wymaga pakietu deepspeed)")
    p.add_argument("--graj", action="store_true", help="odtwórz wynik po wygenerowaniu (pojedynczy plik)")
    args = p.parse_args()
    fmt = args.format

    # 1) zbuduj listę zadań: [(nazwa_źródła, tekst, ścieżka_wyjścia), ...]
    def wy_domyslne():
        return Path(args.output).expanduser() if args.output else Path.cwd() / f"mowa.{fmt}"

    zadania: list[tuple[str, str, Path]] = []
    if args.tekst is not None:
        zadania.append(("(tekst)", args.tekst, wy_domyslne()))
    elif args.schowek:
        zadania.append(("(schowek)", tekst_ze_schowka(), wy_domyslne()))
    else:
        pliki = zbierz_pliki(args.wejscie)
        if not pliki:
            sys.exit("Podaj plik(i) .txt/.docx lub folder, albo --schowek / --tekst \"...\". "
                     "Zobacz: ./mow -h")
        katalog = Path(args.katalog_wy).expanduser() if args.katalog_wy else None
        if len(pliki) > 1 and args.output:
            print("  Uwaga: --output ignorowane przy wielu plikach (nazwy wyjść = nazwy wejść).")
        for f in pliki:
            if len(pliki) == 1 and args.output:
                wy = Path(args.output).expanduser()
            else:
                wy = ((katalog / f.name) if katalog else f).with_suffix("." + fmt)
            zadania.append((f.name, tekst_z_pliku(f), wy))

    # 2) głos referencyjny
    glos = Path(args.glos).expanduser()
    if not glos.exists():
        sys.exit(f"Brak próbki głosu: {glos}\n(Przygotuj ją skryptem przygotuj_glos.sh.)")

    # 3) model + odcisk głosu — RAZ dla całej partii
    device = wykryj_urzadzenie(args.urzadzenie)
    ds_info = " + DeepSpeed" if (args.deepspeed and device == "cuda") else ""
    tryb = f"wsadowy ({len(zadania)} plików)" if len(zadania) > 1 else "pojedynczy"
    print(f"Tryb: {tryb}. Ładuję model XTTS-v2 na: {device}{ds_info} "
          f"(pierwsze uruchomienie pobiera ~1.8 GB)...")
    model, sr = zaladuj_model(device, args.deepspeed)
    print("Analizuję próbkę głosu (raz)...")
    odcisk = policz_odcisk(model, glos)

    # 4) synteza każdego zadania (model i odcisk już gotowe)
    wygenerowane: list[Path] = []
    for idx, (nazwa, tekst, wy) in enumerate(zadania, 1):
        fragmenty = na_fragmenty((tekst or "").strip())
        etykieta = f"[{idx}/{len(zadania)}] {nazwa}"
        if not fragmenty:
            print(f"{etykieta}: puste źródło — pomijam.")
            continue
        print(f"{etykieta}: {len(fragmenty)} fragment(ów) → {wy.name}")
        audio = syntezuj(model, sr, fragmenty, odcisk, args.jezyk, args.predkosc)
        zapisz_audio(audio, sr, wy, fmt)
        wygenerowane.append(wy)

    # 5) podsumowanie
    print(f"\nGotowe: {len(wygenerowane)}/{len(zadania)} plików.")
    for wy in wygenerowane:
        print(f"  • {wy}")
    if args.graj and len(wygenerowane) == 1:
        odtworz(wygenerowane[0])
    elif args.graj and len(wygenerowane) > 1:
        print("(--graj pominięte przy wielu plikach)")


if __name__ == "__main__":
    main()
