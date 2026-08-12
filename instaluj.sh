#!/usr/bin/env bash
#
# instaluj.sh — inteligentny instalator narzędzia "mowmoim" (XTTS-v2).
# Wykrywa system i sam dobiera właściwą instalację:
#   • macOS (Apple Silicon)        → PyTorch CPU/MPS, przez Homebrew
#   • Linux + NVIDIA CUDA (i WSL2)  → PyTorch CUDA + opcjonalnie DeepSpeed
#   • Linux bez GPU                 → PyTorch CPU
#
# Tworzy środowisko .venv i instaluje wszystkie zależności. Można uruchamiać
# wielokrotnie (idempotentny). Opcje:
#   --no-deepspeed   nie instaluj DeepSpeed (nawet na CUDA)
#   --cpu            wymuś PyTorch CPU (pomiń CUDA)
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
VENV="$DIR/.venv"

# Utwardzenie pip na macOS: bez tego pip potrafi segfaultować przy sięganiu do
# Keychain przez CoreFoundation po forku ("process has forked..."). Dla publicznego
# PyPI keyring jest zbędny. Zmienne są nieszkodliwe na Linux/WSL.
export PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export no_proxy='*'   # macOS: bez tego pip segfaultuje (SystemConfiguration po forku)

WITH_DEEPSPEED=1
FORCE_CPU=0
for a in "$@"; do
  case "$a" in
    --no-deepspeed) WITH_DEEPSPEED=0 ;;
    --cpu)          FORCE_CPU=1 ;;
    *) echo "Nieznana opcja: $a"; exit 1 ;;
  esac
done

log()  { printf "\033[1;36m[instalator]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[uwaga]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[błąd]\033[0m %s\n" "$*" >&2; }

# ---------------------------------------------------------------- 1) wykrycie
OS="$(uname -s)"; ARCH="$(uname -m)"
PLATFORMA="nieznana"; CUDA=0; WSL=0
case "$OS" in
  Darwin) PLATFORMA="macos" ;;
  Linux)
    PLATFORMA="linux"
    grep -qiE "microsoft|wsl" /proc/version 2>/dev/null && WSL=1
    if [ "$FORCE_CPU" -eq 0 ] && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
      CUDA=1
    fi ;;
  *) err "Nieobsługiwany system: $OS"; exit 1 ;;
esac
OPIS="$PLATFORMA ($ARCH)"; [ $WSL -eq 1 ] && OPIS="$OPIS, WSL2"
[ $CUDA -eq 1 ] && OPIS="$OPIS, CUDA" || { [ "$PLATFORMA" = "linux" ] && OPIS="$OPIS, bez CUDA"; }
log "Wykryto: $OPIS"

# ---------------------------------------------------------------- 2) pakiety systemowe
if [ "$PLATFORMA" = "macos" ]; then
  command -v brew >/dev/null 2>&1 || { err "Brak Homebrew — zainstaluj z https://brew.sh i uruchom ponownie."; exit 1; }
  command -v ffmpeg >/dev/null 2>&1 || { log "Instaluję ffmpeg (brew)..."; brew install ffmpeg; }
  brew list python@3.11 >/dev/null 2>&1 || { log "Instaluję python@3.11 (brew)..."; brew install python@3.11; }
else
  if command -v apt-get >/dev/null 2>&1; then
    PKGS="ffmpeg python3-venv python3-dev"
    [ $CUDA -eq 1 ] && PKGS="$PKGS build-essential libaio-dev"
    log "Pakiety systemowe (sudo apt): $PKGS"
    sudo apt-get update -qq && sudo apt-get install -y -qq $PKGS \
      || warn "Nie udało się doinstalować: $PKGS — zainstaluj ręcznie."
  else
    warn "Brak apt-get. Zainstaluj ręcznie: ffmpeg, python3-venv, python3-dev (oraz build-essential + libaio-dev dla DeepSpeed)."
  fi
fi

# ---------------------------------------------------------------- 3) Python <3.13
znajdz_python() {
  for c in python3.11 python3.12 python3.10 python3.9 python3; do
    command -v "$c" >/dev/null 2>&1 || continue
    if "$c" -c 'import sys; raise SystemExit(0 if (3,9)<=sys.version_info[:2]<(3,13) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}
PY="$(znajdz_python)" || { err "Wymagany Python 3.9–3.12 (coqui-tts nie wspiera 3.13). Zainstaluj np. python3.11."; exit 1; }
log "Interpreter: $PY ($($PY --version 2>&1))"

# ---------------------------------------------------------------- 4) venv
if [ ! -d "$VENV" ]; then log "Tworzę środowisko .venv..."; "$PY" -m venv "$VENV"; fi
# Zawsze przez 'python -m pip' (nie skrypt bin/pip) — odporne na przenoszenie venv.
pip_install() { "$VENV/bin/python" -m pip install "$@"; }
"$VENV/bin/python" -m pip install --upgrade pip -q

# ---------------------------------------------------------------- 5) PyTorch
log "Instaluję PyTorch (torch + torchaudio + torchcodec)..."
if [ "$PLATFORMA" = "macos" ]; then
  pip_install -q torch torchaudio torchcodec                         # buildy MPS/CPU (PyPI)
elif [ $CUDA -eq 1 ]; then
  pip_install -q torch torchaudio torchcodec                         # domyślne wheele Linux = CUDA
else
  pip_install -q --index-url https://download.pytorch.org/whl/cpu torch torchaudio torchcodec
fi

# ---------------------------------------------------------------- 6) coqui-tts + reszta
# UWAGA: transformers MUSI być <5 — od 5.x znika isin_mps_friendly i import TTS pada.
log "Instaluję coqui-tts i zależności..."
pip_install -q "coqui-tts" "transformers>=4.57,<5" python-docx pyperclip soundfile numpy

# ---------------------------------------------------------------- 7) DeepSpeed (opcjonalnie, CUDA)
if [ $CUDA -eq 1 ] && [ $WITH_DEEPSPEED -eq 1 ]; then
  log "Instaluję DeepSpeed (~2x szybciej na CUDA)..."
  pip_install -q deepspeed \
    || warn "DeepSpeed się nie zbudował — narzędzie zadziała bez niego (nie używaj flagi --deepspeed)."
fi

# ---------------------------------------------------------------- 8) weryfikacja
log "Weryfikacja instalacji..."
"$VENV/bin/python" - <<'PY'
import torch
print(f"  torch {torch.__version__} | CUDA: {torch.cuda.is_available()} | MPS: {getattr(torch.backends,'mps',None) and torch.backends.mps.is_available()}")
import TTS, soundfile, numpy, docx, pyperclip           # noqa
print("  coqui-tts + zależności: OK")
try:
    import deepspeed; print(f"  deepspeed {deepspeed.__version__}: OK")
except Exception:
    print("  deepspeed: brak (opcjonalny, tylko CUDA)")
PY

chmod +x "$DIR/mow" "$DIR/przygotuj_glos.sh" 2>/dev/null || true
log "GOTOWE. Przykład:  ./mow --tekst \"Cześć, to działa\" -o test.mp3 --graj"
