# Marek_voice — tekst → mowa w moim głosie

Narzędzie CLI, które zamienia tekst (`.txt`, `.docx` lub schowek systemowy)
na plik audio (`mp3`, `wav`, `m4a`, `ogg`, `flac`) czytany moim sklonowanym
głosem. Działa **lokalnie i offline** na modelu Coqui **XTTS-v2** (Apple Silicon).

## Szybki start

```bash
# aktywacja środowiska
source venv311/bin/activate

# z pliku tekstowego → wyklad.mp3
python mowmoim.py wyklad.txt

# z dokumentu Word → własny plik wav
python mowmoim.py notatka.docx -f wav -o komentarz.wav

# ze schowka (skopiuj tekst, potem uruchom) i od razu odtwórz
python mowmoim.py --schowek --graj

# tekst wpisany wprost
python mowmoim.py --tekst "Dzień dobry, tu Marek." -o powitanie.mp3
```

## Opcje

| Opcja | Znaczenie | Domyślnie |
|-------|-----------|-----------|
| `wejscie` | plik `.txt` lub `.docx` | — |
| `--schowek` | czytaj tekst ze schowka | — |
| `--tekst "..."` | tekst podany wprost | — |
| `-o, --output` | plik wyjściowy | obok wejścia |
| `-f, --format` | `mp3`/`wav`/`m4a`/`ogg`/`flac` | `mp3` |
| `-g, --glos` | próbka głosu (`.wav`) | `glos/Marek_ref.wav` |
| `-j, --jezyk` | język tekstu | `pl` |
| `--predkosc` | tempo mowy (1.0 = normalne) | `1.0` |
| `--urzadzenie` | `cpu`/`mps`/`auto` | `cpu` |
| `--graj` | odtwórz po wygenerowaniu | — |

## Zmiana / poprawa głosu referencyjnego

Jakość klonu zależy od próbki. Najlepiej: **15–30 s** czystej, spokojnej mowy,
bez szumu i muzyki. Aby przygotować próbkę z nowego nagrania:

```bash
./przygotuj_glos.sh /sciezka/do/nagrania.m4a
```

Skrypt normalizuje głośność i zapisuje `glos/Marek_ref.wav` (24 kHz, mono).

## Uwagi

- Pierwsze uruchomienie pobiera model XTTS-v2 (~1.8 GB) do cache i jest wolne;
  kolejne są znacznie szybsze.
- Domyślnie liczy na CPU (najstabilniejsze na macOS). `--urzadzenie mps`
  bywa szybsze, ale część operacji może się nie udać — używaj eksperymentalnie.
- Licencja modelu XTTS-v2 (Coqui Public Model License) ogranicza użycie
  komercyjne — do materiałów dydaktycznych/prywatnych jest w porządku.
```
