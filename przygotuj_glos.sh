#!/bin/bash
# przygotuj_glos.sh — przygotowuje próbkę referencyjną głosu dla XTTS.
# Bierze dowolne nagranie (wav/mp3/m4a), normalizuje głośność, czyści pasmo
# i zapisuje jako glos/Marek_ref.wav (24 kHz, mono) — format optymalny dla XTTS.
#
# Użycie:
#   ./przygotuj_glos.sh                       # użyje domyślnego nagrania
#   ./przygotuj_glos.sh /sciezka/do/nagrania.m4a
#
# Wskazówka: najlepsza próbka to 15–30 s czystej, spokojnej mowy bez szumu,
# muzyki i przydechów. Im czystsza próbka, tym wierniejszy klon.

set -e
KATALOG="$(cd "$(dirname "$0")" && pwd)"
DOMYSLNE="/Users/marekurbaniak/Downloads/data/voice-profiles/Marek_voice.wav"
ZRODLO="${1:-$DOMYSLNE}"
CEL="$KATALOG/glos/Marek_ref.wav"

if [ ! -f "$ZRODLO" ]; then
    echo "BŁĄD: nie znaleziono nagrania: $ZRODLO"
    exit 1
fi

mkdir -p "$KATALOG/glos"
echo "Przygotowuję próbkę z: $ZRODLO"

ffmpeg -hide_banner -loglevel error -y -i "$ZRODLO" \
    -af "loudnorm=I=-18:TP=-2:LRA=11,highpass=f=70,lowpass=f=8500" \
    -ar 24000 -ac 1 "$CEL"

CZAS=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$CEL")
echo "Gotowe: $CEL (${CZAS} s)"
