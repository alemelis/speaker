'use strict';

const queryInput = document.getElementById('query-input');
const searchBtn  = document.getElementById('search-btn');
const statusEl   = document.getElementById('status');
const resultsEl  = document.getElementById('results');

const PLACEHOLDERS = {
  similar_tracks:  'Artist - Track  (e.g. Fu Manchu - Eatin Dust)',
  similar_artists: 'Artist  (e.g. Fu Manchu)',
  song:            'Song title  (e.g. Eatin Dust)',
  discography:     'Artist  (e.g. Fu Manchu)',
};

let mode = 'similar_tracks';

document.querySelectorAll('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    mode = btn.dataset.mode;
    queryInput.placeholder = PLACEHOLDERS[mode];
    queryInput.focus();
    statusEl.classList.add('hidden');
    resultsEl.innerHTML = '';
  });
});

queryInput.placeholder = PLACEHOLDERS[mode];
queryInput.addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
searchBtn.addEventListener('click', run);

async function run() {
  const query = queryInput.value.trim();
  if (!query) return;

  searchBtn.disabled = true;
  searchBtn.textContent = 'Searching…';
  setStatus('Searching…', false);
  resultsEl.innerHTML = '';

  try {
    const res = await fetch('api/discover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, query }),
    });
    let data;
    try { data = await res.json(); }
    catch { setStatus(`Server error (${res.status}).`, true); return; }

    if (!res.ok) { setStatus(data.detail || 'Error.', true); return; }

    const { results = [], result_type, message } = data;
    message ? setStatus(message, false) : statusEl.classList.add('hidden');

    if (result_type === 'tracks')  renderTracks(results);
    if (result_type === 'artists') renderArtists(results);
    if (result_type === 'albums')  renderAlbums(results);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search';
  }
}

// --- Renderers ---

function renderTracks(results) {
  if (!results.length) { resultsEl.innerHTML = '<p class="panel-status">No results.</p>'; return; }
  const el = document.createElement('div');
  el.className = 'results';
  results.forEach(({ title, artist, album }) => {
    const actions = document.createElement('div');
    actions.className = 'row-actions';
    if (album) actions.appendChild(tracksToggle(artist, album));
    actions.appendChild(dlAlbumLink(artist, album));
    const row = makeRow(
      `<span class="r-artist">${esc(artist)}</span>
       <span class="r-title">${esc(title)}</span>
       ${album ? `<span class="r-sub">${esc(album)}</span>` : ''}`,
      actions,
    );
    el.appendChild(row);
    if (album) el.appendChild(makeTracklist(artist, album, row));
  });
  resultsEl.appendChild(el);
}

function renderArtists(results) {
  if (!results.length) { resultsEl.innerHTML = '<p class="panel-status">No results.</p>'; return; }
  const el = document.createElement('div');
  el.className = 'results';
  results.forEach(({ artist }) => {
    const btn = document.createElement('a');
    btn.href = '#';
    btn.className = 'dl-btn';
    btn.textContent = 'Discography';
    btn.addEventListener('click', e => {
      e.preventDefault();
      queryInput.value = artist;
      document.querySelector('[data-mode="discography"]').click();
      run();
    });
    el.appendChild(makeRow(`<span class="r-artist">${esc(artist)}</span>`, btn));
  });
  resultsEl.appendChild(el);
}

function renderAlbums(results) {
  if (!results.length) { resultsEl.innerHTML = '<p class="panel-status">No results.</p>'; return; }
  const el = document.createElement('div');
  el.className = 'results';
  results.forEach(({ artist, album, year }) => {
    const actions = document.createElement('div');
    actions.className = 'row-actions';
    actions.appendChild(tracksToggle(artist, album));
    actions.appendChild(dlAlbumLink(artist, album));
    const row = makeRow(
      `<span class="r-artist">${esc(artist)}</span>
       <span class="r-title">${esc(album)}</span>
       ${year ? `<span class="r-sub">${esc(year)}</span>` : ''}`,
      actions,
    );
    el.appendChild(row);
    el.appendChild(makeTracklist(artist, album, row));
  });
  resultsEl.appendChild(el);
}

function makeRow(metaHtml, actionEl) {
  const row = document.createElement('div');
  row.className = 'result-row';
  const meta = document.createElement('div');
  meta.className = 'result-meta';
  meta.innerHTML = metaHtml;
  row.appendChild(meta);
  row.appendChild(actionEl);
  return row;
}

function dlAlbumLink(artist, album) {
  const params = new URLSearchParams();
  if (artist) params.set('artist', artist);
  if (album)  params.set('album', album);
  const searchQ = [artist, album].filter(Boolean).join(' ');
  if (searchQ) params.set('search', searchQ);
  const a = document.createElement('a');
  a.href = `/download/?${params}`;
  a.target = '_blank';
  a.rel = 'noopener';
  a.className = 'dl-btn';
  a.textContent = album ? 'Download album' : 'Download';
  return a;
}

function tracksToggle(artist, album) {
  const btn = document.createElement('button');
  btn.className = 'dl-btn toggle-btn';
  btn.type = 'button';
  btn.textContent = 'tracks ▸';
  btn.dataset.open = '0';
  btn.addEventListener('click', () => {
    const open = btn.dataset.open === '1';
    btn.dataset.open = open ? '0' : '1';
    btn.textContent = open ? 'tracks ▸' : 'tracks ▾';
    // find the sibling tracklist panel
    const panel = btn.closest('.result-row').nextElementSibling;
    if (panel && panel.classList.contains('tracklist-panel')) {
      panel.classList.toggle('hidden', open);
      if (!open && !panel.dataset.loaded) loadTracklist(panel, artist, album);
    }
  });
  return btn;
}

function makeTracklist(artist, album, _row) {
  const panel = document.createElement('div');
  panel.className = 'tracklist-panel hidden';
  return panel;
}

async function loadTracklist(panel, artist, album) {
  panel.dataset.loaded = '1';
  panel.innerHTML = '<p class="tl-loading">Loading…</p>';
  try {
    const res = await fetch(`api/tracks?artist=${encodeURIComponent(artist)}&album=${encodeURIComponent(album)}`);
    const data = await res.json();
    const tracks = data.tracks || [];
    if (!tracks.length) { panel.innerHTML = '<p class="tl-loading">No tracklist found.</p>'; return; }
    const ol = document.createElement('ol');
    ol.className = 'tracklist';
    tracks.forEach(({ title, duration }) => {
      const li = document.createElement('li');
      li.innerHTML = `<span class="tl-title">${esc(title)}</span>${duration ? `<span class="tl-dur">${fmtDur(duration)}</span>` : ''}`;
      ol.appendChild(li);
    });
    panel.innerHTML = '';
    panel.appendChild(ol);
  } catch {
    panel.innerHTML = '<p class="tl-loading">Failed to load tracklist.</p>';
  }
}

function fmtDur(secs) {
  const m = Math.floor(secs / 60), s = secs % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function setStatus(msg, isError) {
  statusEl.textContent = msg;
  statusEl.className = 'panel-status' + (isError ? ' error' : '');
}

function esc(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
