/* app.js – Charlotte House Finder */

const API       = "";
const PAGE_SIZE = 24;

// ── Area groupings for optgroups ──────────────────────────────
const AREA_GROUPS = [
  { label: "Charlotte",          values: ["charlotte"] },
  { label: "South / Southeast",  values: ["pineville", "fort mill", "rock hill"] },
  { label: "East",               values: ["matthews", "mint hill", "stallings", "weddington", "indian trail"] },
  { label: "North",              values: ["huntersville", "cornelius", "davidson"] },
  { label: "Concord / Cabarrus", values: ["concord", "harrisburg"] },
  { label: "Gaston County",      values: ["gastonia"] },
];

// Property type icons
const PROP_ICONS = {
  "condo":           "🏢",
  "condominium":     "🏢",
  "townhouse":       "🏘",
  "townhome":        "🏘",
  "single family":   "🏡",
  "single-family":   "🏡",
  "multi family":    "🏗",
  "multi-family":    "🏗",
  "apartment":       "🏬",
  "land":            "🌳",
  "mobile":          "🚐",
  "manufactured":    "🚐",
};

function propIcon(type) {
  if (!type) return "🏠";
  const lower = type.toLowerCase();
  for (const [key, icon] of Object.entries(PROP_ICONS)) {
    if (lower.includes(key)) return icon;
  }
  return "🏠";
}

// ── State ─────────────────────────────────────────────────────
let state = {
  listings:            [],
  total:               0,
  offset:              0,
  filterCity:          "",
  filterNeighborhood:  "",
  filterType:          "",
  filterBedrooms:      "",
  filterBathrooms:     "",
  filterMinPrice:      "",
  filterMaxPrice:      "",
  filterMinSqft:       "",
  filterMaxSqft:       "",
  filterSource:        "",
  filterPropertyType:  "",
  sortBy:              "",
  scraping:            false,
  pollTimer:           null,
};

// ── DOM refs ──────────────────────────────────────────────────
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

// ── Utilities ─────────────────────────────────────────────────
function show(el)  { el.classList.remove("hidden"); }
function hide(el)  { el.classList.add("hidden"); }

function fmtDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); }
  catch { return iso; }
}

function fmtPrice(raw) {
  if (!raw || raw === "N/A") return "Price N/A";
  const n = parseFloat(String(raw).replace(/,/g, ""));
  if (isNaN(n)) return raw;
  return "$" + n.toLocaleString();
}

function esc(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ── API helpers ───────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error || res.statusText);
  }
  return res.json();
}

// ── Dropdowns ─────────────────────────────────────────────────
async function loadCities() {
  const areas = await apiFetch("/api/cities");
  const sel   = $("filter-city");

  // Build a map from value → label for easy lookup
  const byValue = {};
  areas.forEach(a => { byValue[a.value] = a.label; });

  const grouped   = new Set();
  const allValues = areas.map(a => a.value);

  AREA_GROUPS.forEach(grp => {
    const matching = grp.values.filter(v => allValues.includes(v));
    if (!matching.length) return;
    const og = document.createElement("optgroup");
    og.label = grp.label;
    matching.forEach(v => {
      og.append(new Option(byValue[v] || v, v));
      grouped.add(v);
    });
    sel.appendChild(og);
  });

  // Any city not in a group → flat "Other" optgroup
  const ungrouped = allValues.filter(v => !grouped.has(v));
  if (ungrouped.length) {
    const og = document.createElement("optgroup");
    og.label = "Other";
    ungrouped.forEach(v => og.append(new Option(byValue[v] || v, v)));
    sel.appendChild(og);
  }
}

async function loadNeighborhoods() {
  try {
    const hoods = await apiFetch("/api/neighborhoods");
    hoods.sort((a, b) => a.label.localeCompare(b.label));
    const sel = $("filter-neighborhood");
    hoods.forEach(h => sel.append(new Option(h.label, h.value)));
  } catch { /* ignore */ }
}

async function loadPropertyTypes() {
  try {
    const types = await apiFetch("/api/property-types");
    const sel = $("filter-property-type");
    types.forEach(t => sel.append(new Option(t, t)));
  } catch { /* ignore */ }
}

// ── Listings ──────────────────────────────────────────────────
async function loadListings() {
  hide(grid);
  hide(stateEmpty);
  hide(stateError);
  hide(pagination);
  show(stateLoading);

  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: state.offset });
  if (state.filterCity)         params.set("city",          state.filterCity);
  if (state.filterNeighborhood) params.set("neighborhood",  state.filterNeighborhood);
  if (state.filterType)         params.set("listing_type",  state.filterType);
  if (state.filterBedrooms)     params.set("bedrooms",      state.filterBedrooms);
  if (state.filterBathrooms)    params.set("bathrooms",     state.filterBathrooms);
  if (state.filterMinPrice)     params.set("min_price",     state.filterMinPrice);
  if (state.filterMaxPrice)     params.set("max_price",     state.filterMaxPrice);
  if (state.filterMinSqft)      params.set("min_sqft",      state.filterMinSqft);
  if (state.filterMaxSqft)      params.set("max_sqft",      state.filterMaxSqft);
  if (state.filterSource)       params.set("source",        state.filterSource);
  if (state.filterPropertyType) params.set("property_type", state.filterPropertyType);
  if (state.sortBy)             params.set("sort_by",       state.sortBy);

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

  const from = state.offset + 1;
  const to   = Math.min(state.offset + state.listings.length, state.total);
  resultCount.textContent = `${from}–${to} of ${state.total.toLocaleString()} listings`;

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

  const parts    = (l.title || "").split(" \u2013 ");
  const addrLine = parts[0] || l.title || "Untitled";
  const cityLine = parts[1] || "";

  const typeBadge = l.listing_type === "for_rent"
    ? `<span class="type-badge type-rent">For Rent</span>`
    : `<span class="type-badge type-sale">For Sale</span>`;

  const srcLabels = {
    redfin: "Redfin", zillow: "Zillow", realtor: "Realtor.com",
    craigslist: "Craigslist", estately: "Estately",
    apartments: "Apartments.com", searchcharlotte: "SearchCharlotte",
  };
  const srcLabel = srcLabels[l.source] || l.source;
  const srcBadge = l.source
    ? `<span class="source-tag source-${esc(l.source)}">${esc(srcLabel)}</span>`
    : "";

  const icon   = propIcon(l.property_type);
  const propTag = l.property_type
    ? `<span class="prop-tag">${icon} ${esc(l.property_type)}</span>`
    : `<span class="prop-tag">${icon}</span>`;

  const meta = [];
  if (l.bedrooms  && l.bedrooms  !== "N/A") meta.push(`<span class="meta-chip">🛏 ${esc(l.bedrooms)} bd</span>`);
  if (l.bathrooms && l.bathrooms !== "N/A") meta.push(`<span class="meta-chip">🚿 ${esc(l.bathrooms)} ba</span>`);
  if (l.sqft      && l.sqft      !== "N/A") meta.push(`<span class="meta-chip">📐 ${Number(l.sqft).toLocaleString()} ft²</span>`);

  const dateStr = l.date_posted
    ? `Listed ${fmtDate(l.date_posted)}`
    : (l.date_scraped ? `Scraped ${fmtDate(l.date_scraped)}` : "");
  const link = l.url
    ? `<a class="card-link" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">View →</a>`
    : "";

  card.innerHTML = `
    <div class="card-img">
      ${srcBadge}
      <div class="card-img-icon">${icon}</div>
    </div>
    <div class="card-info">
      <div class="card-price-row">
        <span class="card-price">${esc(fmtPrice(l.price))}</span>
        ${typeBadge}
      </div>
      <p class="card-address">${esc(addrLine)}</p>
      ${cityLine ? `<p class="card-location">${esc(cityLine)}</p>` : ""}
    </div>
    <div class="card-details">
      <div class="card-meta">${meta.join("")}</div>
      ${propTag}
    </div>
    <div class="card-footer">
      <span class="card-date">${dateStr}</span>
      ${link}
    </div>
  `;
  return card;
}

// ── Scrape ────────────────────────────────────────────────────
async function startScrape() {
  const source   = $("scrape-source").value;
  const listType = $("scrape-type").value;
  const maxPages = parseInt($("scrape-pages").value, 10) || 2;
  const minPrice = $("scrape-min-price").value ? parseInt($("scrape-min-price").value, 10) : null;
  const maxPrice = $("scrape-max-price").value ? parseInt($("scrape-max-price").value, 10) : null;

  try {
    await apiFetch("/api/scrape", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ source, listing_type: listType, max_pages: maxPages, min_price: minPrice, max_price: maxPrice }),
    });
    closeModal("modal-scrape");
    startPolling();
  } catch (err) {
    alert("Could not start scrape: " + err.message);
  }
}

// ── Status polling ────────────────────────────────────────────
function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(pollStatus, 1000);
  pollStatus();
}

async function pollStatus() {
  try {
    const s = await apiFetch("/api/status");
    updateStatusBadge(s);
    renderProgress(s);
    if (!s.running) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      state.offset = 0;
      await loadListings();
      await loadPropertyTypes();  // refresh now that new data is in
    }
  } catch { /* silently ignore */ }
}

function updateStatusBadge(s) {
  statusBadge.className = "status-badge";
  if (s.running) {
    statusBadge.classList.add("status-running");
    statusBadge.textContent = "Scraping…";
  } else if (s.message && s.message.includes("error")) {
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

function renderProgress(s) {
  const wrap    = $("scrape-progress");
  const bar     = $("scrape-progress-bar");
  const label   = $("scrape-progress-label");
  const percent = $("scrape-progress-percent");
  if (!wrap || !bar) return;
  if (!s.running) { hide(wrap); return; }

  const p   = s.progress || {};
  const pct = Math.max(0, Math.min(100, Number(p.percent || 0)));
  bar.style.width = pct + "%";
  percent.textContent = pct.toFixed(0) + "%";

  const parts = [];
  if (p.stage) {
    const sidx = p.source_idx, stot = p.source_total;
    parts.push(sidx && stot ? `${p.stage} (${sidx}/${stot})` : p.stage);
  }
  if (p.detail) {
    const step = p.step, total = p.total;
    parts.push(step && total ? `${p.detail} (${step}/${total})` : p.detail);
  }
  label.textContent = parts.join(" — ") || (s.message || "Working…");
  show(wrap);
}

// ── History ───────────────────────────────────────────────────
async function showHistory() {
  openModal("modal-history");
  const wrap = $("history-table-wrap");
  wrap.innerHTML = "<p class='empty-msg'>Loading…</p>";
  try {
    const rows = await apiFetch("/api/history");
    if (!rows.length) { wrap.innerHTML = "<p class='empty-msg'>No scrape runs recorded yet.</p>"; return; }
    const tableRows = rows.map(r => `
      <tr>
        <td>${fmtDate(r.started_at)}</td>
        <td>${esc(r.city)}</td>
        <td>${r.listings_found ?? 0}</td>
        <td>${r.listings_new ?? 0}</td>
        <td><span class="pill ${r.status === "success" ? "pill-success" : "pill-error"}">${esc(r.status)}</span></td>
      </tr>`).join("");
    wrap.innerHTML = `
      <table class="history-table">
        <thead><tr><th>Date</th><th>Source</th><th>Found</th><th>New</th><th>Status</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>`;
  } catch (err) {
    wrap.innerHTML = `<p class='empty-msg'>Error: ${esc(err.message)}</p>`;
  }
}

// ── Modal helpers ─────────────────────────────────────────────
function openModal(id)  { show($(id)); }
function closeModal(id) { hide($(id)); }

// ── Build export URL from current filters ─────────────────────
function buildExportParams() {
  const p = new URLSearchParams();
  if (state.filterCity)         p.set("city",          state.filterCity);
  if (state.filterNeighborhood) p.set("neighborhood",  state.filterNeighborhood);
  if (state.filterType)         p.set("listing_type",  state.filterType);
  if (state.filterBedrooms)     p.set("bedrooms",      state.filterBedrooms);
  if (state.filterBathrooms)    p.set("bathrooms",     state.filterBathrooms);
  if (state.filterMinPrice)     p.set("min_price",     state.filterMinPrice);
  if (state.filterMaxPrice)     p.set("max_price",     state.filterMaxPrice);
  if (state.filterMinSqft)      p.set("min_sqft",      state.filterMinSqft);
  if (state.filterMaxSqft)      p.set("max_sqft",      state.filterMaxSqft);
  if (state.filterSource)       p.set("source",        state.filterSource);
  if (state.filterPropertyType) p.set("property_type", state.filterPropertyType);
  if (state.sortBy)             p.set("sort_by",       state.sortBy);
  return p;
}

// ── Clear all filters ─────────────────────────────────────────
function clearFilters() {
  const ids = [
    "filter-city", "filter-neighborhood", "filter-type", "filter-property-type",
    "filter-sort", "filter-bedrooms", "filter-bathrooms", "filter-source",
    "filter-min-price", "filter-max-price", "filter-min-sqft", "filter-max-sqft",
  ];
  ids.forEach(id => { if ($(id)) $(id).value = ""; });
  Object.assign(state, {
    filterCity: "", filterNeighborhood: "", filterType: "",
    filterBedrooms: "", filterBathrooms: "", filterMinPrice: "", filterMaxPrice: "",
    filterMinSqft: "", filterMaxSqft: "", filterSource: "", filterPropertyType: "",
    sortBy: "", offset: 0,
  });
  loadListings();
}

// ── Event wiring ──────────────────────────────────────────────
function wireEvents() {
  $("btn-scrape").addEventListener("click",         () => openModal("modal-scrape"));
  $("btn-scrape-confirm").addEventListener("click", startScrape);
  $("btn-history").addEventListener("click",        showHistory);
  $("btn-refresh").addEventListener("click", async () => {
    const btn = $("btn-refresh");
    btn.disabled = true;
    state.offset = 0;
    try { await loadListings(); } finally { btn.disabled = false; }
  });

  document.querySelectorAll(".modal-close").forEach(btn =>
    btn.addEventListener("click", e => closeModal(e.target.dataset.modal)));
  document.querySelectorAll(".modal-overlay").forEach(overlay =>
    overlay.addEventListener("click", e => { if (e.target === overlay) closeModal(overlay.id); }));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape")
      document.querySelectorAll(".modal-overlay:not(.hidden)").forEach(m => closeModal(m.id));
  });

  // Select-based filters (instant reload)
  const selFilters = [
    ["filter-city",          "filterCity"],
    ["filter-neighborhood",  "filterNeighborhood"],
    ["filter-type",          "filterType"],
    ["filter-property-type", "filterPropertyType"],
    ["filter-sort",          "sortBy"],
    ["filter-bedrooms",      "filterBedrooms"],
    ["filter-bathrooms",     "filterBathrooms"],
    ["filter-source",        "filterSource"],
  ];
  selFilters.forEach(([id, key]) => {
    $(id).addEventListener("change", e => {
      state[key]    = e.target.value;
      state.offset  = 0;
      loadListings();
    });
  });

  // Text/number filters (debounced)
  const reloadDb = debounce(() => { state.offset = 0; loadListings(); }, 400);
  [
    ["filter-min-price", "filterMinPrice"],
    ["filter-max-price", "filterMaxPrice"],
    ["filter-min-sqft",  "filterMinSqft"],
    ["filter-max-sqft",  "filterMaxSqft"],
  ].forEach(([id, key]) => {
    $(id).addEventListener("input", e => { state[key] = e.target.value; reloadDb(); });
  });

  $("btn-export").addEventListener("click", () => {
    window.location.href = `/api/export.csv?${buildExportParams()}`;
  });
  $("btn-clear").addEventListener("click", clearFilters);

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
}

// ── Boot ──────────────────────────────────────────────────────
async function init() {
  wireEvents();
  await Promise.all([loadCities(), loadNeighborhoods(), loadPropertyTypes()]);
  await loadListings();
  try {
    const s = await apiFetch("/api/status");
    updateStatusBadge(s);
    if (s.running) startPolling();
  } catch { /* ignore */ }
}

init();
