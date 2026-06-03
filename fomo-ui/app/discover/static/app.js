'use strict';

const queryInput = document.getElementById('query-input');
const searchBtn  = document.getElementById('search-btn');
const statusEl   = document.getElementById('status');
const resultsEl  = document.getElementById('results');

queryInput.addEventListener('keydown', e => { if (e.key === 'Enter') findSimilar(); });
searchBtn.addEventListener('click', findSimilar);

async function findSimilar() {
  const query = queryInput.value.trim();
  if (!query) return;

  searchBtn.disabled = true;
  searchBtn.textContent = 'Searching…';
  setStatus('Looking up similar tracks…', false);
  resultsEl.innerHTML = '';

  try {
    const res = await fetch('api/similar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });

    let data;
    try { data = await res.json(); }
    catch { setStatus(`Server error (${res.status}).`, true); return; }

    if (!res.ok) { setStatus(data.detail || 'Error.', true); return; }

    const { results = [], message } = data;
    message ? setStatus(message, false) : statusEl.classList.add('hidden');
    renderResults(results);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Find similar';
  }
}

function setStatus(msg, isError) {
  statusEl.textContent = msg;
  statusEl.className = 'panel-status' + (isError ? ' error' : '');
}

function renderResults(results) {
  if (!results.length) {
    resultsEl.innerHTML = '<p class="panel-status">No results.</p>';
    return;
  }
  const container = document.createElement('div');
  container.className = 'results';
  results.forEach(({ title, artist, album }) => {
    const row = document.createElement('div');
    row.className = 'result-row';

    const meta = document.createElement('div');
    meta.className = 'result-meta';
    meta.innerHTML =
      `<span class="result-artist">${esc(artist || '?')}</span>` +
      `<span class="result-track">${esc(title || '?')}</span>` +
      (album ? `<span class="result-album">${esc(album)}</span>` : '');

    const params = new URLSearchParams();
    if (artist) params.set('artist', artist);
    if (album)  params.set('album', album);
    const searchQ = [artist, album].filter(Boolean).join(' ');
    if (searchQ) params.set('search', searchQ);

    const btn = document.createElement('a');
    btn.href = `/download/?${params}`;
    btn.target = '_blank';
    btn.rel = 'noopener';
    btn.className = 'dl-btn';
    btn.textContent = album ? 'Download album' : 'Download';

    row.appendChild(meta);
    row.appendChild(btn);
    container.appendChild(row);
  });
  resultsEl.appendChild(container);
}

function esc(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
