'use strict';

// --- Search ---

const searchInput   = document.getElementById('search-input');
const searchBtn     = document.getElementById('search-btn');
const searchResults = document.getElementById('search-results');

searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
searchBtn.addEventListener('click', doSearch);

// Search-as-you-type, debounced so a burst of keystrokes fires one request.
let searchTimer = null;
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (q.length < 2) return;
  searchTimer = setTimeout(doSearch, 300);
});

async function doSearch() {
  const query = searchInput.value.trim();
  if (!query) return;

  searchBtn.disabled = true;
  searchBtn.textContent = 'Searching...';
  searchResults.classList.remove('hidden');
  document.getElementById('search-playlists').innerHTML = '<p class="search-loading">Searching...</p>';
  document.getElementById('search-videos').innerHTML = '';

  try {
    const res = await fetch('api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) {
      document.getElementById('search-playlists').innerHTML = '<p class="search-error">Search failed.</p>';
      return;
    }
    const { videos, playlists } = await res.json();
    renderResultGroup(document.getElementById('search-playlists'), playlists, true);
    renderResultGroup(document.getElementById('search-videos'), videos, false);
  } catch (err) {
    document.getElementById('search-playlists').innerHTML = `<p class="search-error">${err.message}</p>`;
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search';
  }
}

function renderResultGroup(container, results, isPlaylist) {
  if (!results.length) {
    container.innerHTML = '<p class="search-empty">No results.</p>';
    return;
  }
  container.innerHTML = '';
  results.forEach(r => {
    const item = document.createElement('div');
    item.className = 'search-result';
    const sub = isPlaylist ? '' : `${r.channel}${r.duration ? ' · ' + r.duration : ''}`;
    item.innerHTML = `
      <img class="search-thumb" src="${r.thumbnail}" alt="" loading="lazy">
      <div class="search-meta">
        <span class="search-title">${r.title}</span>
        ${sub ? `<span class="search-sub">${sub}</span>` : ''}
      </div>`;
    item.addEventListener('click', () => {
      document.getElementById('url-input').value = r.url;
      if (!isPlaylist) document.getElementById('title-input').value = r.title;
      if (isPlaylist && !playlistCheck.checked) {
        playlistCheck.checked = true;
        playlistCheck.dispatchEvent(new Event('change'));
      }
      searchResults.classList.add('hidden');
      searchInput.value = '';
    });
    container.appendChild(item);
  });
}

// --- Download form ---

const form          = document.getElementById('dl-form');
const playlistCheck = document.getElementById('playlist-check');
const titleField    = document.getElementById('title-field');
const delayField    = document.getElementById('delay-field');
const fetchBtn      = document.getElementById('fetch-btn');
const submitBtn     = document.getElementById('submit-btn');

const trackSection  = document.getElementById('track-section');
const trackCount    = document.getElementById('track-count');
const trackList     = document.getElementById('track-list');
const selAllBtn     = document.getElementById('sel-all-btn');
const selNoneBtn    = document.getElementById('sel-none-btn');
const dlSelectedBtn = document.getElementById('dl-selected-btn');

const progressSection = document.getElementById('progress-section');
const statusLine      = document.getElementById('status-line');
const spinner         = document.getElementById('spinner');
const barWrap         = document.getElementById('bar-wrap');
const barFill         = document.getElementById('bar-fill');
const barLabel        = document.getElementById('bar-label');

const warnLog   = document.getElementById('warn-log');
const errorLog  = document.getElementById('error-log');
const statusMsg = document.getElementById('status-msg');

// --- Mode toggle ---

playlistCheck.addEventListener('change', () => {
  const pl = playlistCheck.checked;
  titleField.classList.toggle('hidden', pl);
  delayField.classList.toggle('hidden', pl);
  fetchBtn.classList.toggle('hidden', !pl);
  submitBtn.classList.toggle('hidden', pl);
  trackSection.classList.add('hidden');
  resetFeedback();
});

// --- Fetch playlist ---

fetchBtn.addEventListener('click', async () => {
  const url = document.getElementById('url-input').value.trim();
  if (!url) return;

  resetFeedback();
  fetchBtn.disabled = true;
  fetchBtn.textContent = 'Fetching...';

  try {
    const res = await fetch('api/playlist-info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const text = await res.text();
      showError(text);
      return;
    }
    const { entries } = await res.json();
    renderTrackList(entries);
    trackSection.classList.remove('hidden');
  } catch (err) {
    showError(err.message);
  } finally {
    fetchBtn.disabled = false;
    fetchBtn.textContent = 'Fetch tracks';
  }
});

function renderTrackList(entries) {
  trackList.innerHTML = '';
  entries.forEach(({ index, title }) => {
    const li = document.createElement('li');
    li.innerHTML = `<label><input type="checkbox" value="${index}" checked> ${title}</label>`;
    trackList.appendChild(li);
  });
  trackCount.textContent = `${entries.length} tracks`;
}

selAllBtn.addEventListener('click',  () => trackList.querySelectorAll('input').forEach(cb => cb.checked = true));
selNoneBtn.addEventListener('click', () => trackList.querySelectorAll('input').forEach(cb => cb.checked = false));

// --- Download selected (playlist) ---

dlSelectedBtn.addEventListener('click', () => {
  const selected = [...trackList.querySelectorAll('input:checked')].map(cb => +cb.value);
  if (!selected.length) return;
  startDownload({ playlist: true, selected_items: selected, total: selected.length });
});

// --- Download single track ---

form.addEventListener('submit', e => {
  e.preventDefault();
  startDownload({ playlist: false, selected_items: [], total: 1 });
});

// --- Core download ---

async function startDownload({ playlist, selected_items, total }) {
  resetFeedback();
  showProgress(playlist, total);

  const body = {
    url:            document.getElementById('url-input').value.trim(),
    artist:         document.getElementById('artist-input').value.trim(),
    album:          document.getElementById('album-input').value.trim(),
    title:          document.getElementById('title-input').value.trim(),
    playlist,
    delay:          parseInt(document.getElementById('delay-input').value, 10) || 0,
    selected_items,
  };

  let res;
  try {
    res = await fetch('api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (err) {
    hideProgress();
    showError(err.message);
    return;
  }

  const { job_id } = await res.json();
  // The job now runs server-side, independent of this page — closing the tab
  // does not stop it. We just watch its progress stream.
  watchJob(job_id, playlist, total);
}

// Subscribe to a job's SSE stream. Safe to call on page load to re-attach to a
// download already in flight. EventSource auto-reconnects, and the server
// replays a snapshot on connect, so progress resumes after navigation.
function watchJob(jobId, playlist, total) {
  showProgress(playlist, total);
  const es = new EventSource(`api/download/${jobId}/events`);

  es.addEventListener('snapshot', e => {
    const s = JSON.parse(e.data);
    showProgress(!!s.playlist, s.total || total || 1);
    updateBar(s.done || 0, s.total || 1);
    if (s.message) statusLine.textContent = s.message;
  });
  es.addEventListener('progress', e => {
    const { done, total } = JSON.parse(e.data);
    updateBar(done, total);
  });
  es.addEventListener('status', e => { statusLine.textContent = e.data; });
  es.addEventListener('warn', e => appendWarn(e.data));
  es.addEventListener('done', () => {
    es.close();
    hideProgress();
    const hasWarns = !warnLog.classList.contains('hidden');
    showStatus('ok', hasWarns ? 'Done (with warnings).' : 'Done.');
  });
  es.addEventListener('failed', e => {
    es.close();
    hideProgress();
    showError(e.data || 'Download failed.');
  });
  es.addEventListener('cancelled', () => {
    es.close();
    hideProgress();
    showStatus('error', 'Cancelled.');
  });
  // Native connection errors (not SSE 'failed' events) carry no data — let
  // EventSource reconnect on its own rather than reporting a failure.
}

// On load, re-attach to any download still running so it shows up even if the
// original tab was closed.
async function reattachRunningJobs() {
  try {
    const res = await fetch('api/downloads');
    if (!res.ok) return;
    const jobs = await res.json();
    const active = jobs.find(j => j.status === 'running' || j.status === 'queued');
    if (active) watchJob(active.job_id, !!active.playlist, active.total || 1);
  } catch { /* ignore */ }
}
reattachRunningJobs();

// --- Progress UI ---

function showProgress(playlist, total) {
  progressSection.classList.remove('hidden');
  if (playlist) {
    spinner.classList.add('hidden');
    barWrap.classList.remove('hidden');
    updateBar(0, total);
  } else {
    barWrap.classList.add('hidden');
    spinner.classList.remove('hidden');
  }
}

function hideProgress() {
  progressSection.classList.add('hidden');
  statusLine.textContent = '';
}

function updateBar(done, total) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  barFill.style.width = pct + '%';
  barLabel.textContent = `${done} / ${total}`;
}

// --- Feedback helpers ---

function showStatus(type, msg) {
  statusMsg.textContent = msg;
  statusMsg.className = `status ${type}`;
  statusMsg.classList.remove('hidden');
}

function appendWarn(msg) {
  warnLog.classList.remove('hidden');
  const li = document.createElement('li');
  li.textContent = msg;
  warnLog.appendChild(li);
}

function showError(log) {
  errorLog.textContent = log;
  errorLog.classList.remove('hidden');
  showStatus('error', 'Download failed.');
}

function resetFeedback() {
  progressSection.classList.add('hidden');
  warnLog.classList.add('hidden');
  warnLog.innerHTML = '';
  errorLog.classList.add('hidden');
  statusMsg.classList.add('hidden');
  errorLog.textContent = '';
}
