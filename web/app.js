/* =====================================================================
   Marek_voice — Studio · logika interfejsu
   ===================================================================== */
const $ = (s) => document.querySelector(s);

const el = {
  led:$('#led'), statusText:$('#statusText'), deviceInfo:$('#deviceInfo'),
  tekst:$('#tekst'), licznik:$('#licznik'),
  dropzone:$('#dropzone'), plikInput:$('#plikInput'), wybierzPlik:$('#wybierzPlik'),
  plikChip:$('#plikChip'), dropLabel:$('#dropLabel'),
  profilSel:$('#profilSel'), formatSel:$('#formatSel'), tempo:$('#tempo'), tempoVal:$('#tempoVal'),
  generuj:$('#generuj'),
  fala:$('#fala'), render:$('#render'), outMeta:$('#outMeta'),
  play:$('#play'), tc:$('#tc'), pobierz:$('#pobierz'), audio:$('#audio'),
  profilList:$('#profilList'),
  meter:$('#meter'), recBtn:$('#recBtn'), recLabel:$('#recLabel'), recTime:$('#recTime'),
  recPreview:$('#recPreview'), recSave:$('#recSave'), recNazwa:$('#recNazwa'), zapiszProfil:$('#zapiszProfil'),
  trim:$('#trim'), trimWrap:$('#trimWrap'), trimFala:$('#trimFala'), shadeL:$('#shadeL'), shadeR:$('#shadeR'),
  handleL:$('#handleL'), handleR:$('#handleR'), trimPlay:$('#trimPlay'), trimPlayBtn:$('#trimPlayBtn'),
  trimInfo:$('#trimInfo'),
  toast:$('#toast'),
};

let aktywnyProfil = null;
let wczytanyPlik = null;      // File .docx (parsowany po stronie serwera)
let falaPeaks = null;         // szczyty do rysowania fali
let recDuration = 0;          // długość nagranej próbki (s)
let trimL = 0, trimR = 1;     // pozycje uchwytów przycięcia (0..1)
let recPeaks = null;          // szczyty fali próbki

/* ── pomocnicze ───────────────────────────────────────────────── */
function toast(msg, typ='') {
  el.toast.textContent = msg; el.toast.className = 'toast ' + typ;
  el.toast.hidden = false; requestAnimationFrame(() => el.toast.classList.add('show'));
  clearTimeout(toast._t); toast._t = setTimeout(() => {
    el.toast.classList.remove('show'); setTimeout(() => el.toast.hidden = true, 260);
  }, 3200);
}
const czas = (s) => {
  if (!isFinite(s)) s = 0;
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return `${String(m).padStart(2,'0')}:${String(r).padStart(2,'0')}`;
};

/* ── status + inicjalizacja ───────────────────────────────────── */
async function odswiezStatus() {
  try {
    const r = await fetch('/api/status'); const d = await r.json();
    el.led.className = 'led ' + (d.gotowy ? 'ok' : 'warm');
    el.statusText.textContent = d.gotowy ? 'silnik ciepły' : 'silnik gotowy (zimny)';
    el.deviceInfo.textContent = 'urządzenie: ' + (d.urzadzenie || 'auto');
    wypelnijFormaty(d.formaty);
    renderProfile(d.profile);
  } catch (e) {
    el.led.className = 'led err'; el.statusText.textContent = 'brak połączenia z serwerem';
  }
}
function wypelnijFormaty(formaty) {
  if (el.formatSel.options.length) return;
  (formaty || ['mp3','wav']).forEach(f => {
    const o = document.createElement('option'); o.value = o.textContent = f; el.formatSel.appendChild(o);
  });
}

/* ── profile ──────────────────────────────────────────────────── */
function renderProfile(profile) {
  el.profilList.innerHTML = '';
  if (!profile.length) {
    el.profilList.innerHTML = '<li style="cursor:default;color:var(--txt-dim)">Brak profili — nagraj próbkę poniżej.</li>';
  }
  if (!profile.includes(aktywnyProfil)) aktywnyProfil = profile[0] || null;

  profile.forEach(nazwa => {
    const li = document.createElement('li');
    li.className = nazwa === aktywnyProfil ? 'active' : '';
    li.innerHTML = `<span class="p-dot"></span><span class="p-name"></span>
                    <button class="p-del" title="usuń profil">✕</button>`;
    li.querySelector('.p-name').textContent = nazwa;
    li.onclick = (ev) => { if (ev.target.classList.contains('p-del')) return; ustawProfil(nazwa); };
    li.querySelector('.p-del').onclick = (ev) => { ev.stopPropagation(); usunProfil(nazwa); };
    el.profilList.appendChild(li);
  });

  // rozwijana lista GŁOS
  el.profilSel.innerHTML = '';
  profile.forEach(n => {
    const o = document.createElement('option'); o.value = o.textContent = n;
    if (n === aktywnyProfil) o.selected = true; el.profilSel.appendChild(o);
  });
}
function ustawProfil(nazwa) {
  aktywnyProfil = nazwa;
  [...el.profilList.children].forEach(li =>
    li.classList.toggle('active', li.querySelector('.p-name')?.textContent === nazwa));
  el.profilSel.value = nazwa;
}
async function usunProfil(nazwa) {
  if (!confirm(`Usunąć profil „${nazwa}"?`)) return;
  const r = await fetch('/api/profile/' + encodeURIComponent(nazwa), { method:'DELETE' });
  if (r.ok) { const d = await r.json(); renderProfile(d.profile); toast('Usunięto profil: ' + nazwa, 'ok'); }
  else toast('Nie udało się usunąć profilu', 'err');
}
el.profilSel.onchange = () => ustawProfil(el.profilSel.value);

/* ── licznik + wejście tekstu/pliku ───────────────────────────── */
function aktualizujLicznik() {
  const n = el.tekst.value.trim().length;
  const fragm = n ? Math.max(1, Math.ceil(n / 200)) : 0;
  el.licznik.textContent = `${n} znaków · ~${fragm} fragm.`;
}
el.tekst.addEventListener('input', aktualizujLicznik);

el.wybierzPlik.onclick = () => el.plikInput.click();
el.plikInput.onchange = () => obsluzPlik(el.plikInput.files[0]);

function obsluzPlik(file) {
  if (!file) return;
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (ext === 'docx') {                    // .docx parsuje serwer — trzymamy plik
    wczytanyPlik = file; pokazChip(file.name);
  } else {                                 // .txt/.md — wczytaj do pola
    const fr = new FileReader();
    fr.onload = () => { el.tekst.value = fr.result; aktualizujLicznik(); wczytanyPlik = null; ukryjChip(); };
    fr.readAsText(file, 'utf-8');
    toast('Wczytano: ' + file.name, 'ok');
  }
}
function pokazChip(nazwa) {
  el.plikChip.innerHTML = `📄 ${nazwa} <span class="x" title="usuń">✕</span>`;
  el.plikChip.hidden = false; el.dropLabel.hidden = true;
  el.plikChip.querySelector('.x').onclick = () => { wczytanyPlik = null; ukryjChip(); };
}
function ukryjChip() { el.plikChip.hidden = true; el.dropLabel.hidden = false; }

['dragover','dragenter'].forEach(ev => el.dropzone.addEventListener(ev, e => {
  e.preventDefault(); el.dropzone.classList.add('drag');
}));
['dragleave','drop'].forEach(ev => el.dropzone.addEventListener(ev, e => {
  e.preventDefault(); el.dropzone.classList.remove('drag');
}));
el.dropzone.addEventListener('drop', e => obsluzPlik(e.dataTransfer.files[0]));

el.tempo.oninput = () => el.tempoVal.textContent = (+el.tempo.value).toFixed(2) + '×';

/* ── generowanie ──────────────────────────────────────────────── */
el.generuj.onclick = async () => {
  if (!aktywnyProfil) return toast('Najpierw wybierz lub nagraj profil głosu', 'err');
  const fd = new FormData();
  fd.append('profil', aktywnyProfil);
  fd.append('format', el.formatSel.value);
  fd.append('predkosc', el.tempo.value);
  if (wczytanyPlik) fd.append('plik', wczytanyPlik);
  else {
    if (!el.tekst.value.trim()) return toast('Wpisz tekst albo wczytaj plik', 'err');
    fd.append('text', el.tekst.value);
  }

  el.generuj.disabled = true; el.render.hidden = false; el.led.className = 'led warm';
  el.statusText.textContent = 'renderowanie…';
  try {
    const r = await fetch('/api/mowa', { method:'POST', body:fd });
    if (!r.ok) { const t = await r.json().catch(() => ({})); throw new Error(t.detail || ('HTTP ' + r.status)); }
    const blob = await r.blob();
    await zaladujWynik(blob, el.formatSel.value);
    toast('Gotowe — wygenerowano audio', 'ok');
  } catch (e) {
    toast('Błąd generowania: ' + e.message, 'err');
  } finally {
    el.generuj.disabled = false; el.render.hidden = true; odswiezStatus();
  }
};

async function zaladujWynik(blob, format) {
  const url = URL.createObjectURL(blob);
  const ustawCzas = () => {
    el.tc.textContent = `00:00 / ${czas(el.audio.duration)}`;
    el.outMeta.textContent = `${format.toUpperCase()} · ${czas(el.audio.duration)}`;
  };
  el.audio.onloadedmetadata = ustawCzas;    // podpinamy PRZED src (unikamy wyścigu)
  el.audio.src = url;
  el.pobierz.href = url; el.pobierz.download = 'mowa.' + format; el.pobierz.hidden = false;
  el.play.disabled = false;
  await rysujFale(blob);
  if (el.audio.readyState >= 1 && isFinite(el.audio.duration)) ustawCzas();  // gdy metadane już gotowe
}

/* ── wizualizacja fali ────────────────────────────────────────── */
function ctx2d(c) {
  const r = c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  c.width = r.width * dpr; c.height = r.height * dpr;
  const x = c.getContext('2d'); x.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { x, w: r.width, h: r.height };
}
let _ac = null;
function audioCtx() {
  if (!_ac || _ac.state === 'closed') _ac = new (window.AudioContext || window.webkitAudioContext)();
  return _ac;
}
async function rysujFale(blob) {
  try {
    const buf = await blob.arrayBuffer();
    const audio = await audioCtx().decodeAudioData(buf);
    const data = audio.getChannelData(0);
    const w = el.fala.getBoundingClientRect().width || 600;
    const slupki = Math.max(60, Math.floor(w / 3));
    const krok = Math.max(1, Math.floor(data.length / slupki));
    const peaks = [];
    for (let i = 0; i < slupki; i++) {
      let max = 0;
      for (let j = 0; j < krok; j++) { const v = Math.abs(data[i * krok + j] || 0); if (v > max) max = v; }
      peaks.push(max);
    }
    falaPeaks = peaks;
  } catch (e) { console.warn('rysujFale:', e); falaPeaks = null; }
  malujFale(0);
}
function malujFale(post) {
  const { x, w, h } = ctx2d(el.fala);
  x.clearRect(0, 0, w, h);
  if (!falaPeaks) return;
  const mid = h / 2, bw = w / falaPeaks.length, playX = post * w;
  falaPeaks.forEach((p, i) => {
    const bx = i * bw, bh = Math.max(2, p * (h * 0.82));
    x.fillStyle = bx <= playX ? '#ff9e3d' : '#586576';
    x.fillRect(bx + bw * 0.18, mid - bh / 2, Math.max(1, bw * 0.64), bh);
  });
  // linia playheada
  x.fillStyle = 'rgba(255,158,61,.9)'; x.fillRect(playX, 0, 1.5, h);
}
el.fala.addEventListener('click', e => {
  if (!el.audio.duration) return;
  const r = el.fala.getBoundingClientRect();
  el.audio.currentTime = ((e.clientX - r.left) / r.width) * el.audio.duration;
});

/* ── transport ────────────────────────────────────────────────── */
el.play.onclick = () => el.audio.paused ? el.audio.play() : el.audio.pause();
el.audio.onplay = () => el.play.textContent = '❚❚';
el.audio.onpause = () => el.play.textContent = '▶';
el.audio.onended = () => { el.play.textContent = '▶'; malujFale(0); };
el.audio.ontimeupdate = () => {
  const p = el.audio.currentTime / (el.audio.duration || 1);
  malujFale(p);
  el.tc.textContent = `${czas(el.audio.currentTime)} / ${czas(el.audio.duration)}`;
};
window.addEventListener('resize', () => {
  malujFale(el.audio.currentTime / (el.audio.duration || 1));
  if (!el.trim.hidden) rysujTrimFale();
});

/* ── nagrywarka próbki głosu ──────────────────────────────────── */
let mediaRec = null, recChunks = [], recStream = null, recBlob = null;
let recAC = null, rafMeter = null, recStart = 0, recTimerId = null;

el.recBtn.onclick = () => mediaRec && mediaRec.state === 'recording' ? stopRec() : startRec();

async function startRec() {
  try {
    recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    return toast('Brak dostępu do mikrofonu — zezwól w przeglądarce', 'err');
  }
  recChunks = [];
  mediaRec = new MediaRecorder(recStream);
  mediaRec.ondataavailable = e => e.data.size && recChunks.push(e.data);
  mediaRec.onstop = () => {
    recBlob = new Blob(recChunks, { type: mediaRec.mimeType || 'audio/webm' });
    el.recPreview.src = URL.createObjectURL(recBlob); el.recPreview.hidden = false;
    el.recSave.hidden = false;
    pokazEdytorPrzyciecia();
  };
  mediaRec.start();

  el.recBtn.classList.add('on'); el.recLabel.textContent = 'STOP';
  el.recPreview.hidden = true; el.recSave.hidden = true; el.trim.hidden = true;
  recStart = Date.now();
  recTimerId = setInterval(() => el.recTime.textContent = czas((Date.now() - recStart) / 1000), 200);
  startMeter();
}
function stopRec() {
  if (mediaRec && mediaRec.state === 'recording') mediaRec.stop();
  recStream?.getTracks().forEach(t => t.stop());
  el.recBtn.classList.remove('on'); el.recLabel.textContent = 'NAGRAJ';
  clearInterval(recTimerId); stopMeter();
}
function startMeter() {
  recAC = new (window.AudioContext || window.webkitAudioContext)();
  const src = recAC.createMediaStreamSource(recStream);
  const an = recAC.createAnalyser(); an.fftSize = 128; src.connect(an);
  const dane = new Uint8Array(an.frequencyBinCount);
  const rysuj = () => {
    an.getByteFrequencyData(dane);
    const { x, w, h } = ctx2d(el.meter);
    x.clearRect(0, 0, w, h);
    const bw = w / dane.length;
    for (let i = 0; i < dane.length; i++) {
      const bh = (dane[i] / 255) * h;
      x.fillStyle = '#ff4d5e'; x.globalAlpha = 0.35 + (dane[i] / 255) * 0.65;
      x.fillRect(i * bw, h - bh, bw * 0.8, bh);
    }
    x.globalAlpha = 1;
    rafMeter = requestAnimationFrame(rysuj);
  };
  rysuj();
}
function stopMeter() {
  cancelAnimationFrame(rafMeter);
  recAC?.close(); recAC = null;
  const { x, w, h } = ctx2d(el.meter); x.clearRect(0, 0, w, h);
}

/* ── edytor przycięcia próbki ─────────────────────────────────── */
async function pokazEdytorPrzyciecia() {
  recPeaks = null; recDuration = 0;
  try {
    const audio = await audioCtx().decodeAudioData(await recBlob.arrayBuffer());
    recDuration = audio.duration;
    const data = audio.getChannelData(0);
    const w = el.trimFala.getBoundingClientRect().width || 300;
    const slupki = Math.max(60, Math.floor(w / 2));
    const krok = Math.max(1, Math.floor(data.length / slupki));
    recPeaks = [];
    for (let i = 0; i < slupki; i++) {
      let mx = 0;
      for (let j = 0; j < krok; j++) { const v = Math.abs(data[i * krok + j] || 0); if (v > mx) mx = v; }
      recPeaks.push(mx);
    }
  } catch (e) {
    console.warn('trim decode:', e);
    recDuration = el.recPreview.duration || 0;
  }
  trimL = 0; trimR = 1;
  el.trim.hidden = false;
  rysujTrimFale();
  updatePrzyciecie();
}

function rysujTrimFale() {
  const { x, w, h } = ctx2d(el.trimFala);
  x.clearRect(0, 0, w, h);
  if (!recPeaks) return;
  const mid = h / 2, bw = w / recPeaks.length;
  x.fillStyle = '#66788a';
  recPeaks.forEach((p, i) => {
    const bh = Math.max(2, p * (h * 0.8));
    x.fillRect(i * bw + bw * 0.15, mid - bh / 2, Math.max(1, bw * 0.7), bh);
  });
}

function updatePrzyciecie() {
  el.handleL.style.left = (trimL * 100) + '%';
  el.handleR.style.left = (trimR * 100) + '%';
  el.shadeL.style.width = (trimL * 100) + '%';
  el.shadeR.style.width = ((1 - trimR) * 100) + '%';
  const a = trimL * recDuration, b = trimR * recDuration;
  el.trimInfo.textContent = `${a.toFixed(2)}–${b.toFixed(2)} s  (${(b - a).toFixed(2)} s)`;
}

function przeciagUchwyt(handle, ktory) {
  handle.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    const rect = el.trimWrap.getBoundingClientRect();
    const move = (ev) => {
      let f = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
      const min = 0.02;
      if (ktory === 'L') trimL = Math.min(f, trimR - min);
      else trimR = Math.max(f, trimL + min);
      updatePrzyciecie();
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
}
przeciagUchwyt(el.handleL, 'L');
przeciagUchwyt(el.handleR, 'R');

el.trimPlayBtn.onclick = () => {
  if (!recDuration) return;
  const b = trimR * recDuration;
  el.recPreview.currentTime = trimL * recDuration;
  el.recPreview.play();
  const tick = () => {
    if (el.recPreview.paused || el.recPreview.currentTime >= b) {
      el.recPreview.pause();
      el.recPreview.removeEventListener('timeupdate', tick);
      el.trimPlay.style.opacity = 0;
      return;
    }
    el.trimPlay.style.left = (el.recPreview.currentTime / recDuration * 100) + '%';
    el.trimPlay.style.opacity = 1;
  };
  el.recPreview.addEventListener('timeupdate', tick);
};

el.zapiszProfil.onclick = async () => {
  const nazwa = el.recNazwa.value.trim();
  if (!nazwa) return toast('Podaj nazwę profilu', 'err');
  if (!recBlob) return toast('Najpierw nagraj próbkę', 'err');
  const fd = new FormData();
  fd.append('nazwa', nazwa);
  fd.append('plik', recBlob, 'probka.webm');
  if (recDuration) {
    fd.append('start', (trimL * recDuration).toFixed(3));
    fd.append('koniec', (trimR * recDuration).toFixed(3));
  }
  el.zapiszProfil.disabled = true;
  try {
    const r = await fetch('/api/profile', { method: 'POST', body: fd });
    if (!r.ok) { const t = await r.json().catch(() => ({})); throw new Error(t.detail || ('HTTP ' + r.status)); }
    const d = await r.json();
    renderProfile(d.profile); ustawProfil(d.profil);
    el.recSave.hidden = true; el.recPreview.hidden = true; el.trim.hidden = true;
    el.recNazwa.value = ''; el.recTime.textContent = '00:00';
    toast('Zapisano profil: ' + d.profil, 'ok');
  } catch (e) {
    toast('Błąd zapisu profilu: ' + e.message, 'err');
  } finally {
    el.zapiszProfil.disabled = false;
  }
};

/* ── start ────────────────────────────────────────────────────── */
aktualizujLicznik();
odswiezStatus();
