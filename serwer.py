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
import html as _html
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
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


# =====================================================================
#  Samowystarczalny konwerter Markdown → HTML (dla strony /help).
#  Bez zależności zewnętrznych: obsługuje nagłówki, tabele GFM, bloki kodu
#  (także wcięte w punktach listy), listy, linie poziome, **pogrubienie**,
#  `kod`, [odnośniki](url) i akapity. Zachowuje encje HTML (np. &nbsp;).
# =====================================================================
def _md_inline(text: str) -> str:
    text = re.sub(r"&(?!#?[A-Za-z0-9]+;)", "&amp;", text)      # nie ruszaj encji
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    kody: list[str] = []
    def _stash(m):
        kody.append("<code>" + m.group(1) + "</code>")
        return f"{len(kody) - 1}"
    text = re.sub(r"`([^`]+)`", _stash, text)                  # `kod` — chroń przed dalszym parsem
    text = re.sub(r"\*\*([^*]+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = re.sub(r"(\d+)", lambda m: kody[int(m.group(1))], text)
    return text


def _md_fence(lines: list[str], i: int) -> tuple[int, str]:
    m = re.match(r"^(\s*)```(\w*)\s*$", lines[i])
    indent, lang = len(m.group(1)), m.group(2)
    i += 1
    buf: list[str] = []
    while i < len(lines) and not re.match(r"^\s*```\s*$", lines[i]):
        buf.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i])
        i += 1
    i += 1  # pomiń zamykające ```
    kod = _html.escape("\n".join(buf), quote=False)
    klasa = f' class="lang-{lang}"' if lang else ""
    return i, f"<pre><code{klasa}>{kod}</code></pre>"


def _md_is_sep(line: str) -> bool:
    s = line.strip()
    return bool(s) and set(s) <= set("|-: ") and "-" in s and "|" in s


def _md_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _md_list(lines: list[str], i: int) -> tuple[int, str]:
    tag = "ol" if re.match(r"^\s*\d+\.\s+", lines[i]) else "ul"
    items: list[str] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        m = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", line)
        if m:
            items.append(_md_inline(m.group(1))); i += 1; continue
        if re.match(r"^\s+```", line) and items:          # blok kodu wewnątrz punktu
            i, kod = _md_fence(lines, i); items[-1] += kod; continue
        if not line.strip():                              # pusta linia → sprawdź kontynuację listy
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and re.match(r"^\s*(?:[-*]|\d+\.)\s+", lines[j]):
                i = j; continue
            break
        break
    return i, f"<{tag}>" + "".join(f"<li>{it}</li>" for it in items) + f"</{tag}>"


def _md_do_html(md: str) -> str:
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1; continue
        if re.match(r"^\s*```", line):                                    # blok kodu
            i, h = _md_fence(lines, i); out.append(h); continue
        if "|" in line and i + 1 < n and _md_is_sep(lines[i + 1]):        # tabela GFM
            head = _md_row(line); i += 2; rows = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(_md_row(lines[i])); i += 1
            th = "".join(f"<th>{_md_inline(c)}</th>" for c in head)
            body = "".join("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="tbl"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>')
            continue
        mh = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)                # nagłówek
        if mh:
            lv = len(mh.group(1)); out.append(f"<h{lv}>{_md_inline(mh.group(2))}</h{lv}>"); i += 1; continue
        if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):                 # linia pozioma
            out.append("<hr>"); i += 1; continue
        if re.match(r"^\s*(?:[-*]|\d+\.)\s+", line):                      # lista
            i, h = _md_list(lines, i); out.append(h); continue
        buf = [line]; i += 1                                             # akapit
        while i < n and lines[i].strip() and not re.match(r"^\s*(```|#{1,6}\s|[-*]\s|\d+\.\s)", lines[i]) \
                and not ("|" in lines[i] and i + 1 < n and _md_is_sep(lines[i + 1])):
            buf.append(lines[i]); i += 1
        out.append("<p>" + _md_inline(" ".join(s.strip() for s in buf)) + "</p>")
    return "\n".join(out)


_HELP_SHELL = """<!doctype html>
<html lang="pl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clone-my-voice — Pomoc</title>
<style>
:root{--bg:#0b0d10;--panel:#14181e;--panel2:#191e26;--line:#252c36;--line2:#313a46;
 --txt:#e7ecf2;--txt-dim:#8b97a6;--amber:#ff9e3d;--amber-soft:#ffbb6b;--cyan:#37c6d0;
 --code:#0f1216;--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
 --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
[data-theme="light"]{--bg:#eef1f5;--panel:#fff;--panel2:#eef2f7;--line:#dde3ea;--line2:#cbd4de;
 --txt:#1b2430;--txt-dim:#5f6b7a;--amber:#c96f10;--amber-soft:#e08a2a;--cyan:#0f8f9b;--code:#f4f6f9;}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--txt);font-family:var(--sans);line-height:1.65;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:0 22px 80px}
.doc-top{position:sticky;top:0;display:flex;align-items:center;gap:14px;padding:16px 0 12px;
 background:linear-gradient(180deg,var(--bg) 72%,transparent);z-index:5}
.doc-top a.back{color:var(--amber);text-decoration:none;font-family:var(--mono);font-size:13px;
 border:1px solid var(--line2);padding:7px 12px;border-radius:8px;background:var(--panel2)}
.doc-top a.back:hover{border-color:var(--amber)}
.doc-top .tt{margin-left:auto;cursor:pointer;color:var(--txt-dim);background:var(--panel2);
 border:1px solid var(--line2);border-radius:8px;padding:7px 12px;font-family:var(--mono);font-size:13px}
.doc-top .tt:hover{color:var(--amber);border-color:var(--amber)}
.doc h1{font-size:30px;line-height:1.25;margin:18px 0 6px;letter-spacing:.005em}
.doc h2{font-size:22px;margin:38px 0 10px;padding-top:14px;border-top:1px solid var(--line)}
.doc h3{font-size:17px;margin:26px 0 8px;color:var(--amber-soft)}
.doc h4{font-size:14px;margin:20px 0 6px;font-family:var(--mono);letter-spacing:.06em;color:var(--txt-dim);text-transform:uppercase}
.doc p{margin:12px 0}
.doc a{color:var(--cyan)}
.doc strong{color:var(--txt);font-weight:700}
.doc ul,.doc ol{margin:12px 0;padding-left:24px}
.doc li{margin:6px 0}
.doc li>pre{margin:10px 0}
.doc code{font-family:var(--mono);font-size:.88em;background:var(--code);border:1px solid var(--line);
 border-radius:5px;padding:1.5px 6px;color:var(--amber-soft)}
.doc pre{background:var(--code);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
 overflow:auto}
.doc pre code{background:none;border:none;padding:0;color:var(--txt);font-size:13px;line-height:1.6}
.doc hr{border:none;border-top:1px solid var(--line);margin:30px 0}
.doc .tbl{overflow-x:auto;margin:16px 0;border:1px solid var(--line);border-radius:10px}
.doc table{border-collapse:collapse;width:100%;font-size:14px}
.doc th,.doc td{text-align:left;padding:10px 13px;border-bottom:1px solid var(--line);vertical-align:top}
.doc thead th{background:var(--panel2);font-family:var(--mono);font-size:12px;letter-spacing:.05em;
 text-transform:uppercase;color:var(--txt-dim)}
.doc tbody tr:last-child td{border-bottom:none}
.doc tbody tr:hover{background:var(--panel2)}
</style></head>
<body>
<script>try{document.documentElement.setAttribute('data-theme',localStorage.getItem('motyw')||'dark')}catch(e){document.documentElement.setAttribute('data-theme','dark')}</script>
<div class="wrap">
  <div class="doc-top">
    <a class="back" href="/">← wróć do aplikacji</a>
    <button class="tt" onclick="var d=document.documentElement,x=d.getAttribute('data-theme')==='light'?'dark':'light';d.setAttribute('data-theme',x);try{localStorage.setItem('motyw',x)}catch(e){}">motyw</button>
  </div>
  <article class="doc">{{BODY}}</article>
</div>
</body></html>"""


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


@app.get("/help", response_class=HTMLResponse)
def pomoc():
    """Renderuje README.md jako ładną stronę HTML (nowa karta w GUI)."""
    md = DIR / "README.md"
    if not md.exists():
        raise HTTPException(404, "Brak README.md")
    return HTMLResponse(_HELP_SHELL.replace("{{BODY}}", _md_do_html(md.read_text(encoding="utf-8"))))


# GUI (statyczne pliki) — montowane na końcu, by nie przesłaniać tras /api/*
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MOWA_PORT", "8000"))
    print(f"[serwer] http://127.0.0.1:{port}  (Ctrl+C aby zatrzymać)")
    uvicorn.run(app, host="127.0.0.1", port=port)
