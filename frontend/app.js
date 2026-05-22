/* app.js – Housing Scraper frontend logic */

const API = "";          // same origin; Flask serves both API and static files
const PAGE_SIZE = 24;

// ── State ─────────────────────────────────────────────────────────────────
let state = {
  listings: [],
  total: 0,
  offset: 0,
  filterCity: "",
  filterBedrooms: "",
  scraping: false,
  pollTimer: null,
};

// ── DOM refs ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const grid          = $("listings-grid");
const stateLoading  = $("state-loading");
const stateEmpty    = $("state-empty");
const stateError    = $("state-error");
const stateErrorMsg = $("state-error-msg");
const statusBadge   = $("status-badge");
const resultCount   = $("result-count");
const pagination    = $("pagination");
const pageInfo      = $("page-info");
const btnPrev       = $("btn-prev");
const btnNext       = $("btn-next");

// ── Utilities ─────────────────────────────────────────────────────────────
function show(el)  { el.classList.remove("hidden"); }
function hide(el)  { el.classList.add("hidden"); }
function toggle(el, visible) { visible ? show(el) : hide(el); }

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short", day: "numeric", year: "numeric",
    });
  } catch { return iso; }
}

function cityLabel(cities, value) {
  const c = cities.find(c => c.value === value);
  return c ? c.label : value;
}

// ── API helpers ───────────────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error || res.statusText);
  }
  return res.json();
}

// ── Cities ────────────────────────────────────────────────────────────────
let citiesCache = [];

async function loadCities() {
  citiesCache = await apiFetch("/api/cities");

  // populate filter select
  const filterSel = $("filter-city");
  citiesCache.forEach(c => {
    const opt = new Option(c.label, c.value);
    filterSel.append(opt);
  });

  // populate scrape modal select
  const scrapeSel = $("scrape-city");
  citiesCache.forEach(c => {
    const opt = new Option(c.label, c.value);
    scrapeSel.append(opt);
  });
}

// ── Listings ──────────────────────────────────────────────────────────────
async function loadListings() {
  hide(grid);
  hide(stateEmpty);
  hide(stateError);
  hide(pagination);
  show(stateLoading);

  const params = new URLSearchParams({
    limit: PAGE_SIZE,
    offset: state.offset,
  });
  if (state.filterCity)     params.set("city",     state.filterCity);
  if (state.filterBedrooms) params.set("bedrooms", state.filterBedrooms);

  try {
    const data = await apiFetch(`/api/listings?${params}`);
    state.listings = data.listings;
    state.total    = data.total;
    renderListings();
  } catch (err) {
    hide(stateLoading);
    stateErrorMsg.textContent = err.message;
    show(stateError);
  }
}

function renderListings() {
  hide(stateLoading);
  grid.innerHTML = "";

  if (state.listings.length === 0) {
    show(stateEmpty);
    resultCount.textContent = "";
    return;
  }

  state.listings.forEach(l => grid.appendChild(buildCard(l)));
  show(grid);

  // Result count
  const from = state.offset + 1;
  const to   = Math.min(state.offset + state.listings.length, state.total);
  resultCount.textContent = `Showing ${from}–${to} of ${state.total.toLocaleString()} listings`;

  // Pagination
  const totalPages  = Math.ceil(state.total / PAGE_SIZE);
  const currentPage = Math.floor(state.offset / PAGE_SIZE) + 1;
  if (totalPages > 1) {
    pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
    btnPrev.disabled = state.offset === 0;
    btnNext.disabled = state.offset + PAGE_SIZE >= state.total;
    show(pagination);
  }
}

function buildCard(l) {
  const card = document.createElement("article");
  card.className = "card";

  const price = l.price && l.price !== "N/A" ? l.price : "Price N/A";
  const cLabel = cityLabel(citiesCache, l.city) || l.city || "";

  const metaItems = [];
  if (l.location && l.location !== "N/A")
    metaItems.push(`<span class="card-meta-item">📍 ${esc(l.location)}</span>`);
  if (l.bedrooms && l.bedrooms !== "N/A")
    metaItems.push(`<span class="card-meta-item">🛏 ${esc(l.bedrooms)} br</span>`);
  if (l.sqft && l.sqft !== "N/A")
    metaItems.push(`<span class="card-meta-item">📐 ${esc(l.sqft)} ft²</span>`);

  const scraped = l.date_scraped ? `Scraped ${fmtDate(l.date_scraped)}` : "";
  const link    = l.url
    ? `<a class="card-link" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">View →</a>`
    : "";

  card.innerHTML = `
    <div class="card-header">
      <span class="card-price">${esc(price)}</span>
      ${cLabel ? `<span class="card-city-tag">${esc(cLabel)}</span>` : ""}
    </div>
    <div class="card-body">
      <p class="card-title">${esc(l.title || "Untitled")}</p>
      <div class="card-meta">${metaItems.join("")}</div>
    </div>
    <div class="card-footer">
      <span class="card-date">${scraped}</span>
      ${link}
    </div>
  `;
  return card;
}

function esc(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Scrape ────────────────────────────────────────────────────────────────
async function startScrape() {
  const city     = $("scrape-city").value;
  const maxPages = parseInt($("scrape-pages").value, 10) || 2;

  try {
    await apiFetch("/api/scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ city, max_pages: maxPages }),
    });
    closeModal("modal-scrape");
    startPolling();
  } catch (err) {
    alert("Could not start scrape: " + err.message);
  }
}

// ── Status polling ────────────────────────────────────────────────────────
function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(pollStatus, 3000);
  pollStatus(); // immediate first check
}

async function pollStatus() {
  try {
    const s = await apiFetch("/api/status");
    updateStatusBadge(s);

    if (!s.running) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      // Reload listings to show new results
      state.offset = 0;
      await loadListings();
    }
  } catch {
    // silently ignore poll errors
  }
}

function updateStatusBadge(s) {
  statusBadge.className = "status-badge";
  if (s.running) {
    statusBadge.classList.add("status-running");
    statusBadge.textContent = "Scraping…";
  } else if (s.message && s.message.startsWith("Error")) {
    statusBadge.classList.add("status-error");
    statusBadge.textContent = "Error";
  } else if (s.last_run) {
    statusBadge.classList.add("status-done");
    statusBadge.textContent = "Up to date";
  } else {
    statusBadge.classList.add("status-idle");
    statusBadge.textContent = "Idle";
  }
}

// ── History ───────────────────────────────────────────────────────────────
async function showHistory() {
  openModal("modal-history");
  const wrap = $("history-table-wrap");
  wrap.innerHTML = "<p class='empty-msg'>Loading…</p>";

  try {
    const rows = await apiFetch("/api/history");
    if (rows.length === 0) {
      wrap.innerHTML = "<p class='empty-msg'>No scrape runs recorded yet.</p>";
      return;
    }
    const tableRows = rows.map(r => `
      <tr>
        <td>${fmtDate(r.started_at)}</td>
        <td>${esc(cityLabel(citiesCache, r.city) || r.city)}</td>
        <td>${r.listings_found ?? 0}</td>
        <td>${r.listings_new ?? 0}</td>
        <td><span class="pill ${r.status === 'success' ? 'pill-success' : 'pill-error'}">${esc(r.status)}</span></td>
      </tr>
    `).join("");
    wrap.innerHTML = `
      <table class="history-table">
        <thead>
          <tr><th>Date</th><th>City</th><th>Found</th><th>New</th><th>Status</th></tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
    `;
  } catch (err) {
    wrap.innerHTML = `<p class='empty-msg'>Error: ${esc(err.message)}</p>`;
  }
}

// ── Modal helpers ─────────────────────────────────────────────────────────
function openModal(id)  { show($(id)); }
function closeModal(id) { hide($(id)); }

// ── Event wiring ──────────────────────────────────────────────────────────
function wireEvents() {
  // Scrape button → open modal
  $("btn-scrape").addEventListener("click", () => openModal("modal-scrape"));

  // Confirm scrape
  $("btn-scrape-confirm").addEventListener("click", startScrape);

  // History
  $("btn-history").addEventListener("click", showHistory);

  // Close buttons (any button with class modal-close)
  document.querySelectorAll(".modal-close").forEach(btn => {
    btn.addEventListener("click", e => closeModal(e.target.dataset.modal));
  });

  // Close modal on overlay click
  document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", e => {
      if (e.target === overlay) closeModal(overlay.id);
    });
  });

  // Filters
  $("filter-city").addEventListener("change", e => {
    state.filterCity = e.target.value;
    state.offset = 0;
    loadListings();
  });
  $("filter-bedrooms").addEventListener("change", e => {
    state.filterBedrooms = e.target.value;
    state.offset = 0;
    loadListings();
  });
  $("btn-clear").addEventListener("click", () => {
    $("filter-city").value     = "";
    $("filter-bedrooms").value = "";
    state.filterCity     = "";
    state.filterBedrooms = "";
    state.offset = 0;
    loadListings();
  });

  // Pagination
  btnPrev.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    loadListings();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  btnNext.addEventListener("click", () => {
    state.offset += PAGE_SIZE;
    loadListings();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  // Keyboard: ESC closes modal
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal-overlay:not(.hidden)").forEach(m => closeModal(m.id));
    }
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────
async function init() {
  wireEvents();
  await loadCities();
  await loadListings();

  // Check if a scrape is already running
  try {
    const s = await apiFetch("/api/status");
    updateStatusBadge(s);
    if (s.running) startPolling();
  } catch { /* ignore */ }
}

init();
