'use strict';

const coverflowEl     = document.getElementById('coverflow');
const cfPrevBtn       = document.getElementById('cf-prev');
const cfNextBtn       = document.getElementById('cf-next');
const cfLabel         = document.getElementById('cf-label');
const cfLabelAlbum    = document.getElementById('cf-label-album');
const cfLabelArtist   = document.getElementById('cf-label-artist');
const detailEl        = document.getElementById('detail');
const detailCover     = document.getElementById('detail-cover');
const detailArtist    = document.getElementById('detail-artist');
const detailAlbum     = document.getElementById('detail-album');
const detailYear      = document.getElementById('detail-year');
const detailTracklist = document.getElementById('detail-tracklist');
const statusEl        = document.getElementById('status');

let albums    = [];
let activeIdx = -1;

// ---- layout constants ----
const TILE_W     = 170;   // px — matches CSS .cover-tile width
const SPREAD     = 82;    // px between tile left-edges when fanned
const MAX_ANGLE  = 72;    // max rotateY degrees for far tiles
const VISIBLE_R  = 7;     // tiles rendered on each side of active

// ---- helpers ----

function setStatus(msg, isError) {
  statusEl.textContent = msg;
  statusEl.className = 'status-bar' + (isError ? ' error' : '');
  statusEl.classList.remove('hidden');
}

function fmtDur(ms) {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ---- tile construction ----

function makeTile(album, idx) {
  const tile = document.createElement('div');
  tile.className = 'cover-tile';
  tile.dataset.idx = String(idx);

  if (album.art) {
    const img = document.createElement('img');
    img.alt = '';
    img.loading = 'lazy';
    img.src = '/artwork/?u=' + encodeURIComponent(album.art);
    img.onerror = () => { img.remove(); tile.appendChild(makePlaceholder(album)); };
    tile.appendChild(img);
  } else {
    tile.appendChild(makePlaceholder(album));
  }

  tile.addEventListener('click', () => selectIdx(idx));
  return tile;
}

function makePlaceholder(album) {
  const ph = document.createElement('div');
  ph.className = 'tile-placeholder';
  ph.innerHTML =
    `<span class="tile-album">${esc(album.album)}</span>` +
    `<span class="tile-artist">${esc(album.artist)}</span>`;
  return ph;
}

// ---- 3D coverflow layout ----

function applyFlowTransforms() {
  const tiles = coverflowEl.querySelectorAll('.cover-tile');
  const cx    = coverflowEl.offsetWidth / 2 - TILE_W / 2;

  tiles.forEach(tile => {
    const i    = parseInt(tile.dataset.idx, 10);
    const dist = i - activeIdx;
    const abs  = Math.abs(dist);

    if (abs > VISIBLE_R) {
      tile.style.opacity       = '0';
      tile.style.pointerEvents = 'none';
      return;
    }

    // Horizontal position: centre tile sits at cx, others fan out
    const x = cx + dist * SPREAD;

    // Fold angle: 0 for active, grows for distant tiles
    const angle = dist === 0 ? 0
      : dist < 0 ?  Math.min(MAX_ANGLE, 48 + (abs - 1) * 9)
      :            -Math.min(MAX_ANGLE, 48 + (abs - 1) * 9);

    // Visual cues: active slightly larger, far tiles fade out
    const scale   = dist === 0 ? 1.08 : 1;
    const opacity = abs === 0 ? 1 : abs === 1 ? 0.82 : abs <= 3 ? 0.6 : abs <= 5 ? 0.35 : 0.15;
    const zIdx    = 100 - abs * 8;

    tile.style.left        = `${x}px`;
    tile.style.transform   = `rotateY(${angle}deg) scale(${scale})`;
    tile.style.zIndex      = String(zIdx);
    tile.style.opacity     = String(opacity);
    tile.style.pointerEvents = '';
  });
}

// ---- selection & detail ----

function selectIdx(i) {
  if (i < 0 || i >= albums.length) return;
  activeIdx = i;
  applyFlowTransforms();

  const album = albums[i];

  // Update the label strip
  cfLabelAlbum.textContent  = album.album;
  cfLabelArtist.textContent = album.artist;
  cfLabel.classList.remove('hidden');

  showDetail(album);
}

function showDetail(album) {
  detailArtist.textContent = album.artist;
  detailAlbum.textContent  = album.album;
  detailYear.textContent   = album.year || '';

  if (album.art) {
    detailCover.src          = '/artwork/?u=' + encodeURIComponent(album.art);
    detailCover.style.display = '';
  } else {
    detailCover.style.display = 'none';
  }

  detailTracklist.innerHTML = '<li class="tl-loading">Loading…</li>';
  detailEl.classList.remove('hidden');
  detailTracklist.closest('.tracklist-wrap').scrollTop = 0;

  fetch('api/album/' + encodeURIComponent(album.id) + '/tracks')
    .then(r => r.json())
    .then(data => {
      const tracks = data.tracks || [];
      if (!tracks.length) {
        detailTracklist.innerHTML = '<li class="tl-loading">No tracks found.</li>';
        return;
      }
      detailTracklist.innerHTML = '';
      tracks.forEach(({ track_number, title, length_ms }) => {
        const li = document.createElement('li');
        li.innerHTML =
          `<span class="tl-title">${track_number ? `${track_number}. ` : ''}${esc(title)}</span>` +
          (length_ms ? `<span class="tl-dur">${fmtDur(length_ms)}</span>` : '');
        detailTracklist.appendChild(li);
      });
    })
    .catch(() => {
      detailTracklist.innerHTML = '<li class="tl-loading">Failed to load tracklist.</li>';
    });
}

// ---- navigation ----

cfPrevBtn.addEventListener('click', () => selectIdx(activeIdx - 1));
cfNextBtn.addEventListener('click', () => selectIdx(activeIdx + 1));

coverflowEl.addEventListener('keydown', e => {
  if (e.key === 'ArrowRight') { e.preventDefault(); selectIdx(activeIdx + 1); }
  if (e.key === 'ArrowLeft')  { e.preventDefault(); selectIdx(activeIdx - 1); }
});

window.addEventListener('resize', () => {
  if (activeIdx >= 0) applyFlowTransforms();
});

// ---- init ----

(async () => {
  setStatus('Loading library…', false);
  try {
    const res = await fetch('api/albums');
    if (!res.ok) { setStatus('Failed to load albums.', true); return; }
    const data = await res.json();
    albums = data.albums || [];
    if (!albums.length) { setStatus('No albums found.', false); return; }

    statusEl.classList.add('hidden');
    albums.forEach((album, i) => coverflowEl.appendChild(makeTile(album, i)));

    // Wait one frame so offsetWidth is available before positioning
    requestAnimationFrame(() => {
      selectIdx(0);
      coverflowEl.focus();
    });
  } catch (err) {
    setStatus(err.message, true);
  }
})();
