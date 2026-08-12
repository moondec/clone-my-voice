# Marek_voice — tekst → mowa w moim głosie

Narzędzie CLI zamieniające tekst (`.txt`, `.docx` lub schowek systemowy) na plik
audio (`mp3`, `wav`, `m4a`, `ogg`, `flac`) czytany moim **sklonowanym głosem**.
Działa **lokalnie i offline** na modelu Coqui **XTTS-v2**.

Jedna baza kodu działa na trzech platformach — instalator sam wykrywa środowisko:

| Platforma | Urządzenie | DeepSpeed | Typowa szybkość |
|-----------|-----------|-----------|-----------------|
| **macOS** (Apple Silicon) | CPU | ❌ (brak na Macu) | ~0.5× real-time |
| **Linux / WSL2 + NVIDIA** | CUDA | ✅ (~2×) | ~6–8× real-time |
| **Linux bez GPU** | CPU | ❌ | ~1–1.5× real-time |

---

## 1. Wymagania

Wspólne (instaluje `instaluj.sh`): **Python 3.9–3.12** (NIE 3.13 — coqui-tts go nie
wspiera), `ffmpeg`, oraz pakiety Pythona: `coqui-tts`, `transformers<5`, `torch`,
`torchaudio`, `torchcodec`, `soundfile`, `numpy`, `python-docx`, `pyperclip`.

Zależne od platformy:

- **macOS:** [Homebrew](https://brew.sh) (dostarcza `python@3.11` i `ffmpeg`).
- **Linux / WSL2:** `apt` (dostarcza `ffmpeg`, `python3-venv`, `python3-dev`; dla
  DeepSpeed dodatkowo `build-essential`, `libaio-dev`).
- **CUDA (Linux/WSL2):** sterownik NVIDIA **na hoście** + działające `nvidia-smi`.
  Karta ~4–6 GB VRAM w zupełności wystarcza (XTTS jest mały).

---

## 2. Instalacja (jedna komenda)

```bash
./instaluj.sh
```

Skrypt sam wykryje macOS / Linux / WSL2 oraz obecność CUDA i dobierze właściwe
pakiety. Jest **idempotentny** — można uruchamiać wielokrotnie. Opcje:

```bash
./instaluj.sh --no-deepspeed   # nie instaluj DeepSpeed (nawet na CUDA)
./instaluj.sh --cpu            # wymuś PyTorch CPU (pomiń CUDA)
```

Po instalacji sprawdź, że wszystko gra — na końcu wypisze wersję `torch`
i status CUDA/MPS/DeepSpeed.

---

## 3. Użycie

Najprościej przez launcher `./mow` (uruchamia narzędzie w `.venv`):

```bash
./mow wyklad.txt                       # → wyklad.mp3 (nazwa jak pliku wejściowego)
./mow notatka.docx -f wav -o kom.wav   # Word → WAV, własna nazwa
./mow --schowek --graj                 # ze schowka + odtwórz
./mow --tekst "Dzień dobry, tu Marek." -o powitanie.mp3
```

### Opcje

| Opcja | Znaczenie | Domyślnie |
|-------|-----------|-----------|
| `wejscie` | plik `.txt` lub `.docx` | — |
| `--schowek` | czytaj tekst ze schowka | — |
| `--tekst "..."` | tekst podany wprost | — |
| `-o, --output` | plik wyjściowy | nazwa jak wejścia |
| `-f, --format` | `mp3`/`wav`/`m4a`/`ogg`/`flac` | `mp3` |
| `-g, --glos` | próbka głosu (`.wav`) | `glos/Marek_ref.wav` |
| `-j, --jezyk` | język tekstu | `pl` |
| `--predkosc` | tempo mowy (1.0 = normalne) | `1.0` |
| `--urzadzenie` | `auto`/`cpu`/`cuda`/`mps` | `auto` |
| `--deepspeed` | DeepSpeed (tylko CUDA, ~2×) | — |
| `--graj` | odtwórz po wygenerowaniu | — |

### Wybór urządzenia (`auto`)

`auto` wybiera **CUDA**, jeśli jest dostępna, w przeciwnym razie **CPU**.
Na Apple Silicon celowo NIE wybiera `mps` — dla XTTS (model autoregresyjny) MPS
jest tam wolniejszy niż CPU. Na maszynie z NVIDIA dodaj `--deepspeed` dla ~2×:

```bash
./mow wyklad.txt --deepspeed           # Linux/WSL2 + CUDA
```

---

## 4. Migracja między platformami (Mac ⇄ WSL/Linux)

Cały projekt jest przenośny; środowisko `.venv` i cache modelu są **poza** repo.
Aby uruchomić na nowej maszynie:

1. Skopiuj katalog projektu (lub `git clone`). **Nie** kopiuj `.venv/` —
   jest platformowo-zależne; zostanie odtworzone.
2. Uruchom `./instaluj.sh`.
3. Gotowe: `./mow wyklad.txt`.

Model XTTS-v2 (~1,7 GB) pobierze się automatycznie przy pierwszym uruchomieniu do
`~/Library/Application Support/tts` (macOS) lub `~/.local/share/tts` (Linux).
Możesz go skopiować ręcznie, by uniknąć ponownego pobierania.

### WSL2 — ważne wskazówki

- **Trzymaj projekt WEWNĄTRZ systemu plików WSL** (`~/Marek_voice`), NIE na
  `/mnt/c/...` — dysk przez granicę Windows↔Linux jest bardzo wolny.
- Sterownik NVIDIA instaluj **tylko na Windows**; w WSL tylko CUDA toolkit.
  Sprawdź: `nvidia-smi` musi działać w terminalu WSL.
- Rekomendowane Ubuntu **22.04 lub 24.04** (nie 20.04 — stary Python/CUDA).

---

## 5. Głos referencyjny

Jakość klonu zależy od próbki. Najlepiej **15–30 s** czystej, spokojnej mowy bez
szumu i muzyki. Przygotowanie próbki z dowolnego nagrania:

```bash
./przygotuj_glos.sh /sciezka/do/nagrania.m4a
```

Skrypt normalizuje głośność, czyści pasmo i zapisuje `glos/Marek_ref.wav`
(24 kHz, mono) — format optymalny dla XTTS.

---

## 6. Rozwiązywanie problemów

| Objaw | Przyczyna / rozwiązanie |
|-------|------------------------|
| `backend not found` / stary błąd | to relikt LocalAI — nie dotyczy tej wersji |
| import TTS pada na `isin_mps_friendly` | za nowy `transformers` — musi być `<5` (instalator pilnuje) |
| `torchcodec ... required` | torch ≥2.9 wymaga `torchcodec` (instalator go dodaje) |
| pip **segfault** na macOS (`process has forked`) | ustaw `export no_proxy='*'` (instalator to robi) |
| `bad interpreter: .../venv311/...` | używaj `python -m pip`, nie skryptu `bin/pip` (dotyczy przenoszonego venv) |
| Python 3.13 | coqui-tts go nie wspiera — użyj 3.11/3.12 |
| DeepSpeed nie instaluje się na Windows | użyj **WSL2**, nie natywnego Windows |

---

## 7. Uwagi

- Pierwsze uruchomienie pobiera model (~1,8 GB) i jest wolne; kolejne tylko
  wczytują go z dysku (offline).
- Licencja modelu XTTS-v2 (Coqui Public Model License) ogranicza użycie
  komercyjne — do materiałów dydaktycznych/prywatnych jest w porządku.
