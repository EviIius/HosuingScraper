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
  "condo": "🏢", "condominium": "🏢",
  "townhouse": "🏘", "townhome": "🏘",
  "single family": "🏡", "single-family": "🏡",
  "multi family": "🏗", "multi-family": "🏗",
  "apartment": "🏬",
  "land": "🌳",
  "mobile": "🚐", "manufactured": "🚐",
};

function propIcon(type) {
  if (!type) return "🏠";
  const lower = type.toLowerCase();
  for (const [key, icon] of Object.entries(PROP_ICONS)) {
    if (lower.includes(key)) return icon;
  }
  return "🏠";
}

// ── Charlotte-metro ZIP centroids ──────────────────────────────
const ZIP_CENTROIDS = {
  "28202": [35.2271, -80.8431], "28203": [35.2154, -80.8597],
  "28204": [35.2195, -80.8283], "28205": [35.2258, -80.8077],
  "28206": [35.2447, -80.8308], "28207": [35.2028, -80.8254],
  "28208": [35.2249, -80.8840], "28209": [35.1903, -80.8600],
  "28210": [35.1680, -80.8611], "28211": [35.1847, -80.8210],
  "28212": [35.1835, -80.7900], "28213": [35.2642, -80.7952],
  "28214": [35.2576, -80.9247], "28215": [35.2369, -80.7574],
  "28216": [35.2804, -80.8821], "28217": [35.1739, -80.8880],
  "28226": [35.1436, -80.8589], "28227": [35.1756, -80.7574],
  "28262": [35.3047, -80.7590], "28269": [35.3336, -80.8263],
  "28277": [35.0882, -80.8421], "28278": [35.1227, -80.9386],
  "28031": [35.4897, -80.8619], "28036": [35.4907, -80.7930],
  "28078": [35.4072, -80.8552], "28105": [35.1131, -80.7220],
  "28104": [35.1092, -80.6597], "28110": [35.1260, -80.6500],
  "29708": [35.0980, -81.0024], "29730": [34.9249, -81.0251],
  "28025": [35.4043, -80.5791], "28027": [35.3957, -80.6288],
  "28075": [35.3220, -80.6470],
};

function _hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h >>> 0;
}

function getListingCoords(listing) {
  const zip  = String(listing.zip || "").trim();
  const base = ZIP_CENTROIDS[zip] || [35.2271, -80.8431];
  // Deterministic offset from URL so pins stay in place across refreshes
  const seed = listing.url || listing.title || "";
  const h1   = _hashStr(seed);
  const h2   = _hashStr(seed + "~lng");
  const spread = 0.018; // ~2km spread across each ZIP area
  return [
    base[0] + ((h1 / 0xffffffff) - 0.5) * spread * 2,
    base[1] + ((h2 / 0xffffffff) - 0.5) * spread * 2,
  ];
}

function priceMarkerColor(priceStr) {
  const n = parseFloat(String(priceStr || "").replace(/,/g, ""));
  if (isNaN(n) || n === 0) return "#8b949e";
  if (n < 300000) return "#22d3ee";
  if (n < 400000) return "#4ade80";
  if (n < 500000) return "#86efac";
  if (n < 600000) return "#fbbf24";
  if (n < 700000) return "#f97316";
  return "#f87171";
}

// ── State ─────────────────────────────────────────────────────
let state = {
  listings:            [],
  total:               0,
  offset:              0,
  filterCity:          "",
  filterNeighborhood:  "",
  filterSearch:        "",
  filterZip:           "",
  filterType:          "",
  filterBedrooms:      "",
  filterBathrooms:     "",
  filterMinPrice:      "",
  filterMaxPrice:      "",
  filterMinSqft:       "",
  filterMaxSqft:       "",
  filterSource:        "",
  filterPropertyType:  "",
  filterTag:           "",
  sortBy:              "",
  scraping:            false,
  pollTimer:           null,
  viewMode:            "grid",  // "grid" | "map"
};

// ── DOM refs ──────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const grid           = $("listings-grid");
const mapContainer   = $("map-container");
const tableContainer = $("table-container");
const mapLegend     = $("map-legend");
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

// ── Theme ─────────────────────────────────────────────────────
function applyTheme(theme) {
  document.body.dataset.theme = theme === "light" ? "light" : "";
  $("btn-theme").textContent  = theme === "light" ? "🌙" : "☀️";
  _updateMapTiles();
}

function toggleTheme() {
  const isLight = document.body.dataset.theme === "light";
  const next    = isLight ? "dark" : "light";
  localStorage.setItem("theme", next);
  applyTheme(next);
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
  const byValue = {};
  areas.forEach(a => { byValue[a.value] = a.label; });
  const grouped   = new Set();
  const allValues = areas.map(a => a.value);
  AREA_GROUPS.forEach(grp => {
    const matching = grp.values.filter(v => allValues.includes(v));
    if (!matching.length) return;
    const og = document.createElement("optgroup");
    og.label = grp.label;
    matching.forEach(v => { og.append(new Option(byValue[v] || v, v)); grouped.add(v); });
    sel.appendChild(og);
  });
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
    // Remove dynamic options (keep "All Types")
    while (sel.options.length > 1) sel.remove(1);
    types.forEach(t => sel.append(new Option(t, t)));
  } catch { /* ignore */ }
}

// ── Filter params builder ─────────────────────────────────────
function buildFilterParams(limit, offset) {
  const params = new URLSearchParams({ limit, offset });
  if (state.filterSearch)        params.set("search",        state.filterSearch);
  if (state.filterZip)           params.set("zip_filter",    state.filterZip);
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
  if (state.filterTag)          params.set("user_tag",      state.filterTag);
  if (state.sortBy)             params.set("sort_by",       state.sortBy);
  return params;
}

// ── Listings ──────────────────────────────────────────────────
async function loadListings() {
  if (state.viewMode === "map")   { await loadAndRenderMap(); return; }
  if (state.viewMode === "table") { await loadAndRenderTable(); return; }

  hide(grid); hide(stateEmpty); hide(stateError); hide(pagination);
  show(stateLoading);

  try {
    const data = await apiFetch(`/api/listings?${buildFilterParams(PAGE_SIZE, state.offset)}`);
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
  hide(tableContainer);
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
  if (l.user_tag) card.classList.add(`tagged-${l.user_tag}`);
  card.dataset.id  = l.id;
  card.dataset.tag = l.user_tag || "";

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
    homes: "Homes.com",
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

  const likeActive    = l.user_tag === "liked"    ? " tag-active" : "";
  const dislikeActive = l.user_tag === "disliked" ? " tag-active" : "";

  const imgClass = l.source ? `card-img src-${esc(l.source)}` : "card-img";

  card.innerHTML = `
    <div class="${imgClass}">
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
    <div class="card-actions">
      <button class="tag-btn tag-btn-like${likeActive}" data-tag="liked">
        ♥ Like
      </button>
      <button class="tag-btn tag-btn-dislike${dislikeActive}" data-tag="disliked">
        ✕ Pass
      </button>
    </div>
    <div class="card-footer">
      <span class="card-date">${dateStr}</span>
      ${link}
    </div>
  `;
  return card;
}

// ── Table View ────────────────────────────────────────────────
const TABLE_PAGE_SIZE = 100;
let _tableSort = { col: "price", dir: "desc" };

const TABLE_COLS = [
  { key: "_tag",          label: "Tag",          sortable: false },
  { key: "price",         label: "Price",        sortable: true  },
  { key: "title",         label: "Address",      sortable: true  },
  { key: "city",          label: "City",         sortable: true  },
  { key: "zip",           label: "ZIP",          sortable: true  },
  { key: "bedrooms",      label: "Beds",         sortable: true  },
  { key: "bathrooms",     label: "Baths",        sortable: true  },
  { key: "sqft",          label: "Sqft",         sortable: true  },
  { key: "property_type", label: "Type",         sortable: true  },
  { key: "listing_type",  label: "Sale/Rent",    sortable: false },
  { key: "source",        label: "Source",       sortable: true  },
  { key: "date_scraped",  label: "Scraped",      sortable: true  },
  { key: "url",           label: "Link",         sortable: false },
];

function _tableSortListings(rows) {
  const { col, dir } = _tableSort;
  return [...rows].sort((a, b) => {
    let av = a[col] ?? "", bv = b[col] ?? "";
    if (col === "price" || col === "sqft" || col === "bedrooms" || col === "bathrooms") {
      av = parseFloat(String(av).replace(/,/g, "")) || 0;
      bv = parseFloat(String(bv).replace(/,/g, "")) || 0;
    } else {
      av = String(av).toLowerCase();
      bv = String(bv).toLowerCase();
    }
    if (av < bv) return dir === "asc" ? -1 : 1;
    if (av > bv) return dir === "asc" ? 1 : -1;
    return 0;
  });
}

async function loadAndRenderTable() {
  hide(grid); hide(mapContainer); hide(stateEmpty); hide(stateError); hide(pagination);
  show(stateLoading);

  try {
    const data = await apiFetch(`/api/listings?${buildFilterParams(2000, 0)}`);
    const listings = data.total > 0 ? data.listings : [];

    if (data.total > 2000) {
      const rest = await apiFetch(`/api/listings?${buildFilterParams(data.total, 0)}`);
      listings.push(...rest.listings.slice(2000));
    }

    hide(stateLoading);
    if (listings.length === 0) { show(stateEmpty); resultCount.textContent = ""; return; }

    const sorted = _tableSortListings(listings);
    const srcLabels = {
      redfin: "Redfin", zillow: "Zillow", realtor: "Realtor.com",
      craigslist: "Craigslist", estately: "Estately",
      apartments: "Apartments.com", searchcharlotte: "SearchCharlotte", homes: "Homes.com",
    };

    const thead = TABLE_COLS.map(c => {
      const cls = c.sortable
        ? (_tableSort.col === c.key ? ` class="sort-${_tableSort.dir}"` : "")
        : "";
      const sortAttr = c.sortable ? ` data-col="${c.key}"` : "";
      return `<th${cls}${sortAttr}>${c.label}</th>`;
    }).join("");

    const tbody = sorted.map(l => {
      const addrParts = (l.title || "").split(" – ");
      const addr = addrParts[0] || l.title || "";
      const typeLabel = l.listing_type === "for_rent"
        ? `<span class="type-badge type-rent">Rent</span>`
        : `<span class="type-badge type-sale">Sale</span>`;
      const srcBadge = l.source
        ? `<span class="source-tag source-${esc(l.source)}">${esc(srcLabels[l.source] || l.source)}</span>`
        : "";
      const link = l.url
        ? `<a class="col-link" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">View →</a>`
        : "";
      const likeActive    = l.user_tag === "liked"    ? " tag-active" : "";
      const dislikeActive = l.user_tag === "disliked" ? " tag-active" : "";
      const tagCell = `
        <div class="tbl-tag-btns">
          <button class="tbl-tag-btn tbl-tag-btn-like${likeActive}" data-tag="liked" title="Like">♥</button>
          <button class="tbl-tag-btn tbl-tag-btn-dislike${dislikeActive}" data-tag="disliked" title="Pass">✕</button>
        </div>`;
      const rowClass = l.user_tag ? ` class="tagged-${esc(l.user_tag)}"` : "";
      return `<tr${rowClass} data-id="${l.id}" data-tag="${esc(l.user_tag || "")}">
        <td>${tagCell}</td>
        <td class="col-price">${esc(fmtPrice(l.price))}</td>
        <td class="col-addr" title="${esc(addr)}">${esc(addr)}</td>
        <td>${esc(l.city || "")}</td>
        <td>${esc(l.zip || "")}</td>
        <td>${esc(l.bedrooms || "")}</td>
        <td>${esc(l.bathrooms || "")}</td>
        <td>${l.sqft && l.sqft !== "N/A" ? Number(l.sqft).toLocaleString() : ""}</td>
        <td>${esc(l.property_type || "")}</td>
        <td>${typeLabel}</td>
        <td>${srcBadge}</td>
        <td>${fmtDate(l.date_scraped)}</td>
        <td>${link}</td>
      </tr>`;
    }).join("");

    tableContainer.innerHTML = `
      <table class="listings-table">
        <thead><tr>${thead}</tr></thead>
        <tbody>${tbody}</tbody>
      </table>`;

    tableContainer.querySelectorAll("th[data-col]").forEach(th => {
      th.addEventListener("click", () => {
        const col = th.dataset.col;
        _tableSort = _tableSort.col === col && _tableSort.dir === "desc"
          ? { col, dir: "asc" }
          : { col, dir: "desc" };
        loadAndRenderTable();
      });
    });

    show(tableContainer);
    resultCount.textContent = `${sorted.length.toLocaleString()} listings`;
  } catch (err) {
    hide(stateLoading);
    stateErrorMsg.textContent = err.message;
    show(stateError);
  }
}

// ── Map ───────────────────────────────────────────────────────
let _map        = null;
let _tileLayer  = null;
let _mapMarkers = [];

const TILE_DARK  = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
const TILE_LIGHT = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
const TILE_ATTR  = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>';

function isDarkTheme() {
  return document.body.dataset.theme !== "light";
}

function initMap() {
  if (_map) return;
  show(mapContainer);
  _map = L.map("map-container").setView([35.2271, -80.8431], 11);
  _tileLayer = L.tileLayer(isDarkTheme() ? TILE_DARK : TILE_LIGHT, {
    attribution: TILE_ATTR,
    maxZoom: 19,
  }).addTo(_map);
}

function _updateMapTiles() {
  if (!_map || !_tileLayer) return;
  _tileLayer.setUrl(isDarkTheme() ? TILE_DARK : TILE_LIGHT);
}

async function loadAndRenderMap() {
  hide(grid); hide(stateEmpty); hide(stateError); hide(pagination);
  show(stateLoading);

  try {
    const data = await apiFetch(`/api/listings?${buildFilterParams(5000, 0)}`);
    const listings = data.listings || [];

    hide(stateLoading);

    if (listings.length === 0) {
      show(stateEmpty);
      resultCount.textContent = "";
      return;
    }

    // Deduplicate by address for the map — same property listed on multiple
    // sources would otherwise appear as several scattered jittered pins.
    // Key on normalized address (strip unit formatting noise), keep the entry
    // with the most detail (prefer whichever has beds/baths/sqft filled in).
    const SOURCE_PRIORITY = ["zillow","redfin","realtor","estately","searchcharlotte","homes","apartments","craigslist"];
    function addrKey(l) {
      return (l.title || "").toLowerCase()
        .replace(/\s+/g, " ")
        .replace(/\bapt\.?\b|\bunit\b|\bste\.?\b|\s*#\s*/gi, " ")
        .replace(/\xa0/g, " ")
        .trim();
    }
    const seen = new Map();
    for (const l of listings) {
      const key = addrKey(l);
      if (!seen.has(key)) {
        seen.set(key, { primary: l, sources: [{ source: l.source, url: l.url }] });
        continue;
      }
      const entry = seen.get(key);
      if (l.url && !entry.sources.find(s => s.url === l.url)) {
        entry.sources.push({ source: l.source, url: l.url });
      }
      const existing = entry.primary;
      const existingPri = SOURCE_PRIORITY.indexOf(existing.source);
      const newPri      = SOURCE_PRIORITY.indexOf(l.source);
      const existingDetail = [existing.bedrooms, existing.bathrooms, existing.sqft].filter(Boolean).length;
      const newDetail      = [l.bedrooms,        l.bathrooms,        l.sqft       ].filter(Boolean).length;
      if (newDetail > existingDetail || (newDetail === existingDetail && newPri < existingPri)) {
        entry.primary = l;
      }
    }
    const dedupedListings = Array.from(seen.values());

    initMap();
    show(mapContainer);

    // Clear old markers
    _mapMarkers.forEach(m => m.remove());
    _mapMarkers = [];

    const srcLabels = {
      redfin: "Redfin", zillow: "Zillow", realtor: "Realtor.com",
      craigslist: "Craigslist", estately: "Estately",
      apartments: "Apartments.com", searchcharlotte: "SearchCharlotte",
      homes: "Homes.com",
    };

    dedupedListings.forEach(entry => {
      const l = entry.primary;
      const [lat, lng] = getListingCoords(l);
      const color      = priceMarkerColor(l.price);

      const marker = L.circleMarker([lat, lng], {
        radius:      7,
        fillColor:   color,
        color:       isDarkTheme() ? "#0f1117" : "#fff",
        weight:      1.5,
        opacity:     1,
        fillOpacity: 0.85,
      }).addTo(_map);

      const addrParts = (l.title || "").split(" \u2013 ");
      const addr      = addrParts[0] || l.title || "Unknown address";
      const city      = addrParts[1] || "";
      const meta      = [
        l.bedrooms  && l.bedrooms  !== "N/A" ? `${l.bedrooms} bd` : "",
        l.bathrooms && l.bathrooms !== "N/A" ? `${l.bathrooms} ba` : "",
        l.sqft      && l.sqft      !== "N/A" ? `${Number(l.sqft).toLocaleString()} ft²` : "",
      ].filter(Boolean).join(" · ");

      const viewLinks = entry.sources
        .filter(s => s.url)
        .map(s => `<a class="map-popup-link" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">View on ${esc(srcLabels[s.source] || s.source)} →</a>`)
        .join("<br>");

      marker.bindPopup(`
        <div class="map-popup-price">${esc(fmtPrice(l.price))}</div>
        <div class="map-popup-addr">${esc(addr)}${city ? `, ${esc(city)}` : ""}</div>
        <div class="map-popup-meta">${esc(meta) || "Details unavailable"}</div>
        ${viewLinks ? `<div class="map-popup-links">${viewLinks}</div>` : ""}
      `, { maxWidth: 240 });

      _mapMarkers.push(marker);
    });

    resultCount.textContent = `${dedupedListings.length.toLocaleString()} listing${dedupedListings.length !== 1 ? "s" : ""} on map`;

    // Fit map to markers
    if (_mapMarkers.length > 0) {
      const group = L.featureGroup(_mapMarkers);
      _map.fitBounds(group.getBounds().pad(0.05));
    }
  } catch (err) {
    hide(stateLoading);
    stateErrorMsg.textContent = err.message;
    show(stateError);
  }
}

// ── View switcher ─────────────────────────────────────────────
function setView(mode) {
  state.viewMode = mode;
  state.offset   = 0;

  $("btn-view-grid").classList.toggle("active",  mode === "grid");
  $("btn-view-map").classList.toggle("active",   mode === "map");
  $("btn-view-table").classList.toggle("active", mode === "table");

  hide(grid); hide(mapContainer); hide(tableContainer); hide(mapLegend); hide(pagination);

  if (mode === "map") {
    show(mapLegend);
    loadAndRenderMap();
  } else if (mode === "table") {
    loadAndRenderTable();
  } else {
    loadListings();
  }
}

// ── Stopwatch ─────────────────────────────────────────────────
let _stopwatchTimer = null;
let _stopwatchStart = null;

function _fmtElapsed(ms) {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function startStopwatch() {
  _stopwatchStart = Date.now();
  const el = $("scrape-stopwatch");
  show(el);
  el.textContent = "⏱ 0:00";
  if (_stopwatchTimer) clearInterval(_stopwatchTimer);
  _stopwatchTimer = setInterval(() => {
    el.textContent = "⏱ " + _fmtElapsed(Date.now() - _stopwatchStart);
  }, 1000);
}

function stopStopwatch() {
  if (_stopwatchTimer) { clearInterval(_stopwatchTimer); _stopwatchTimer = null; }
  const el = $("scrape-stopwatch");
  if (_stopwatchStart) el.textContent = "⏱ " + _fmtElapsed(Date.now() - _stopwatchStart) + " ✓";
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
    startStopwatch();
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
      stopStopwatch();
      state.offset = 0;
      await loadListings();
      await loadPropertyTypes();
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
  const p = buildFilterParams(5000, 0);
  p.delete("limit"); p.delete("offset");
  // re-add with export limits
  return new URLSearchParams({ ...Object.fromEntries(buildFilterParams(5000, 0)) });
}

// ── Clear all filters ─────────────────────────────────────────
function clearFilters() {
  const ids = [
    "filter-search", "filter-zip",
    "filter-city", "filter-neighborhood", "filter-type", "filter-property-type",
    "filter-sort", "filter-bedrooms", "filter-bathrooms", "filter-source", "filter-tag",
    "filter-min-price", "filter-max-price", "filter-min-sqft", "filter-max-sqft",
  ];
  ids.forEach(id => { if ($(id)) $(id).value = ""; });
  Object.assign(state, {
    filterSearch: "", filterZip: "", filterCity: "", filterNeighborhood: "", filterType: "",
    filterBedrooms: "", filterBathrooms: "", filterMinPrice: "", filterMaxPrice: "",
    filterMinSqft: "", filterMaxSqft: "", filterSource: "", filterPropertyType: "",
    filterTag: "", sortBy: "", offset: 0,
  });
  loadListings();
}

// ── Tagging ───────────────────────────────────────────────────
async function tagListing(id, tag) {
  await apiFetch(`/api/listings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tag }),
  });
}

// Shared tag-click handler — works for both grid cards and table rows
function _applyTagUI(container, newTag, currentTag, isTable) {
  container.dataset.tag = newTag || "";
  container.classList.toggle("tagged-liked",    newTag === "liked");
  container.classList.toggle("tagged-disliked", newTag === "disliked");
  const btnSel = isTable ? ".tbl-tag-btn" : ".tag-btn";
  container.querySelectorAll(btnSel).forEach(b => b.classList.remove("tag-active"));
  if (newTag) container.querySelector(`${btnSel}[data-tag="${newTag}"]`)?.classList.add("tag-active");
}

async function _handleTagClick(e, isTable) {
  const btnSel = isTable ? ".tbl-tag-btn" : ".tag-btn";
  const btn = e.target.closest(btnSel);
  if (!btn) return;
  const container  = isTable ? btn.closest("tr") : btn.closest(".card");
  if (!container) return;
  const id         = parseInt(container.dataset.id, 10);
  const clickedTag = btn.dataset.tag;
  const currentTag = container.dataset.tag;
  const newTag     = currentTag === clickedTag ? null : clickedTag;

  _applyTagUI(container, newTag, currentTag, isTable);
  try {
    await tagListing(id, newTag);
  } catch {
    _applyTagUI(container, currentTag, newTag, isTable); // rollback
  }
}

// Event delegation — one listener on the grid, one on the table container
function wireTagClicks() {
  grid.addEventListener("click", e => _handleTagClick(e, false));
  tableContainer.addEventListener("click", e => _handleTagClick(e, true));
}

// ── Event wiring ──────────────────────────────────────────────
function wireEvents() {
  $("btn-scrape").addEventListener("click",         () => openModal("modal-scrape"));
  $("btn-scrape-confirm").addEventListener("click", startScrape);
  $("btn-history").addEventListener("click",        showHistory);
  $("btn-theme").addEventListener("click",          toggleTheme);

  $("btn-view-grid").addEventListener("click",  () => setView("grid"));
  $("btn-view-map").addEventListener("click",   () => setView("map"));
  $("btn-view-table").addEventListener("click", () => setView("table"));

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
    ["filter-tag",           "filterTag"],
  ];
  selFilters.forEach(([id, key]) => {
    $(id).addEventListener("change", e => {
      state[key]   = e.target.value;
      state.offset = 0;
      loadListings();
    });
  });

  // Text/number filters (debounced)
  const reloadDb = debounce(() => { state.offset = 0; loadListings(); }, 400);
  [
    ["filter-search",    "filterSearch"],
    ["filter-zip",       "filterZip"],
    ["filter-min-price", "filterMinPrice"],
    ["filter-max-price", "filterMaxPrice"],
    ["filter-min-sqft",  "filterMinSqft"],
    ["filter-max-sqft",  "filterMaxSqft"],
  ].forEach(([id, key]) => {
    $(id).addEventListener("input", e => { state[key] = e.target.value; reloadDb(); });
  });

  $("btn-export").addEventListener("click", () => {
    window.location.href = `/api/export.csv?${buildFilterParams(5000, 0)}`;
  });
  $("btn-clear").addEventListener("click", clearFilters);
  $("btn-clear-db").addEventListener("click", async () => {
    if (!confirm("Delete ALL listings from the database? This cannot be undone.")) return;
    try {
      const res = await apiFetch("/api/listings", { method: "DELETE" });
      state.offset = 0;
      await loadListings();
      await loadPropertyTypes();
      alert(`Deleted ${res.deleted.toLocaleString()} listing${res.deleted !== 1 ? "s" : ""}.`);
    } catch (err) {
      alert("Error clearing database: " + err.message);
    }
  });

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
  // Apply saved theme (default dark)
  const savedTheme = localStorage.getItem("theme") || "dark";
  applyTheme(savedTheme);

  wireEvents();
  wireTagClicks();
  await Promise.all([loadCities(), loadNeighborhoods(), loadPropertyTypes()]);
  await loadListings();
  try {
    const s = await apiFetch("/api/status");
    updateStatusBadge(s);
    if (s.running) startPolling();
  } catch { /* ignore */ }
}

init();
