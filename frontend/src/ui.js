// src/ui.js — render(state) and panel renderers
// render(state) is idempotent: call it on every state change; it updates only what's needed.
import { STATES } from './state.js';
import { CONF, pinColor, coverageBadgeText, deriveCoverage } from './confidence.js';
import { buildNarrativeSections, buildDetailModel, filterVisiblePOIs, cityColorFor, buildScenarioCardData } from './ui-helpers.js';
const SRC_DESC = {
  ONTOLOGIA:   'da ontologia formale',
  CONTESTO:    'da contesto ambientale',
  SPECULATIVO: 'inferenza non verificata',
};
const LOADING_STEPS = [
  'Geocodifica zona',
  'Query ontologia POI',
  'Inferenza rischi (LLM)',
  'Generazione narrativa',
];

const $ = id => document.getElementById(id);

// ── Visibility helper ──────────────────────────────────────────────────────────
const ALL_PANELS = [
  'panel-input', 'panel-scenarios', 'overlay-loading',
  'panel-poi', 'panel-detail', 'panel-narrative', 'panel-base', 'map-hint',
];

function showOnly(...ids) {
  ALL_PANELS.forEach(id => {
    const el = $(id);
    if (el) el.style.display = 'none';
  });
  ids.forEach(id => {
    const el = $(id);
    if (el) el.style.display = '';
  });
}

// ── HTML snippet builders ──────────────────────────────────────────────────────

function confBadgeHTML(level, sm = false) {
  const c = CONF[level] || CONF.speculativo;
  return `<span class="conf-badge ${sm ? 'sm ' : ''}${level}">${c.dot} ${c.label}</span>`;
}

function srcTagHTML(type) {
  return `<span class="src-tag ${type}">[${type}]</span>`;
}

function dotPinHTML(n, level, { dim = false, lg = false } = {}) {
  const color = dim ? '#cfccc3' : pinColor(level);
  const opacity = dim ? 0.5 : 1;
  return `<span class="dot-pin${lg ? ' lg' : ''}" style="background:${color};opacity:${opacity};">${n}</span>`;
}

function srcBorderColor(tag) {
  if (tag === 'ONTOLOGIA')   return 'var(--conf-confermato-color)';
  if (tag === 'CONTESTO')    return 'var(--conf-plausibile-color)';
  return 'var(--conf-speculativo-color)';
}

// ── Header right ──────────────────────────────────────────────────────────────
function renderHeaderRight(state) {
  const el = $('header-right');
  if (!el) return;

  const inResults = [STATES.RESULTS, STATES.FILTER, STATES.DETAIL, STATES.BASE].includes(state.screen);
  if (!inResults) { el.innerHTML = ''; return; }

  const data       = state.data;
  const isCompleto = state.mode === 'completo';
  let html = '';

  if (isCompleto && data) {
    // Derive coverage from canonical fields only — no backend `coverage` field.
    // spec-frontend §Allineamenti tecnici #4.
    const { total, anchored } = deriveCoverage(
      data.confidence_summary || {},
      data.risk_models || []
    );
    const txt = coverageBadgeText(total, anchored);
    html += `<div class="coverage-badge"><span>▣</span><span>${txt}</span></div>`;
    html += `<div style="width:1px;height:24px;background:var(--separator);flex-shrink:0;"></div>`;

    html += `<div class="conf-chips">`;
    ['confermato', 'plausibile', 'speculativo'].forEach(lv => {
      const c  = CONF[lv];
      const on = state.filter === lv;
      const n  = data.confidence_summary?.[lv] ?? 0;
      html += `<button class="conf-chip ${lv}${on ? ' active' : ''}"
        data-filter="${lv}" aria-pressed="${on}">
        ${c.dot} ${c.label} <b>${n}</b>${on ? ' <span aria-hidden="true">✕</span>' : ''}
      </button>`;
    });
    html += `</div>`;
  }

  html += `<div class="mode-toggle">
    <button class="mode-toggle-btn${state.mode === 'completo' ? ' active' : ''}" data-mode="completo">Completo</button>
    <button class="mode-toggle-btn${state.mode === 'base' ? ' active' : ''}" data-mode="base">Base</button>
  </div>`;

  el.innerHTML = html;
}

// ── INPUT / ERROR state ────────────────────────────────────────────────────────
function renderInputPanel(state) {
  const body = document.querySelector('#panel-input .panel-body');
  if (!body) return;
  const err = state.error;

  body.innerHTML = `
    <div class="eyebrow">Analisi zona</div>
    <div>
      <div style="font-size:11.5px;color:var(--ink2);margin-bottom:4px;">
        Città / Zona <span style="color:var(--red)">*</span>
      </div>
      <input id="input-zona" type="text"
        placeholder="es. Roma — Stazione Termini"
        value="${esc(state.lastQuery || '')}"
        aria-label="Città o zona da analizzare"
        aria-invalid="${err ? 'true' : 'false'}"
        style="width:100%;border:1.5px solid ${err ? 'var(--red)' : 'var(--ink)'};
               border-radius:5px;padding:9px 11px;font-size:13.5px;
               font-family:var(--font-sans);color:var(--ink);
               background:${err ? 'var(--red-bg)' : '#fff'};outline:none;">
      ${err ? `<div class="input-error" role="alert"><span aria-hidden="true">✕</span><span>${esc(err)}</span></div>` : ''}
    </div>
    <div>
      <div style="font-size:11.5px;color:var(--ink2);margin-bottom:4px;">
        Domanda
        <span style="font-size:10px;color:var(--mute)">(opzionale · linguaggio naturale)</span>
      </div>
      <textarea id="input-domanda" rows="2"
        placeholder="es. quali rischi ci sono di sera?"
        aria-label="Domanda in linguaggio naturale (opzionale)"
        style="width:100%;border:1.5px solid var(--ink);border-radius:5px;resize:none;
               padding:8px 11px;font-size:13px;font-family:var(--font-sans);
               color:var(--ink);outline:none;"></textarea>
    </div>
    <button id="btn-analyze" class="btn solid" style="justify-content:center;width:100%;">
      Analizza zona →
    </button>
    <div style="border-top:1px solid var(--hair);padding-top:13px;">
      ${legendHTML()}
    </div>
    ${err && state.suggestions?.length ? suggestionsHTML(state.suggestions) : ''}
  `;
}

function legendHTML() {
  const levels = [
    ['confermato',  'Da ontologia, verificabile'],
    ['plausibile',  'Inferito dal contesto, probabile'],
    ['speculativo', 'Ipotetico — richiede verifica'],
  ];
  const srcs = [
    ['ONTOLOGIA',   SRC_DESC.ONTOLOGIA],
    ['CONTESTO',    SRC_DESC.CONTESTO],
    ['SPECULATIVO', SRC_DESC.SPECULATIVO],
  ];
  return `
    <div class="eyebrow" style="margin-bottom:9px;">Legenda confidence</div>
    <div style="display:flex;flex-direction:column;gap:9px;">
      ${levels.map(([lv, d]) => `<div style="display:flex;align-items:center;gap:9px;">
        ${confBadgeHTML(lv, true)}<span style="font-size:11px;color:var(--mute)">${d}</span>
      </div>`).join('')}
    </div>
    <div style="border-top:1px solid var(--hair);padding-top:9px;margin-top:9px;">
      <div class="eyebrow" style="margin-bottom:7px;">Tag fonte</div>
      <div style="display:flex;flex-direction:column;gap:7px;">
        ${srcs.map(([t, d]) => `<div style="display:flex;align-items:center;gap:8px;">
          ${srcTagHTML(t)}<span style="font-size:11px;color:var(--mute)">${d}</span>
        </div>`).join('')}
      </div>
    </div>
  `;
}

function suggestionsHTML(suggestions) {
  return `
    <div style="border-top:1px solid var(--hair);padding-top:12px;">
      <div class="eyebrow" style="margin-bottom:8px;">Zone suggerite</div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        ${suggestions.map(s => `
          <button class="suggestion-btn" data-scenario-id="${s.id}">
            <span style="width:8px;height:8px;border-radius:50%;flex-shrink:0;
              background:${cityColorFor(s.city)};"></span>
            <span><b style="color:${cityColorFor(s.city)}">${esc(s.city)}</b> — ${esc(s.zone)}</span>
            <span style="flex:1"></span>
            <span style="color:var(--mute)">→</span>
          </button>`).join('')}
      </div>
    </div>
  `;
}

function renderScenariosPanel(state, scenarios) {
  const panel  = $('panel-scenarios');
  const header = $('panel-scenarios-header');
  const body   = $('panel-scenarios-body');
  const badge  = $('scenarios-collapsed-badge');
  const label  = $('scenarios-city-agnostic');
  if (!panel) return;

  const open = state.scenarioOpen !== false;
  panel.classList.toggle('collapsed', !open);
  if (header) {
    header.querySelector('.toggle-arrow').textContent = open ? '▾' : '▸';
    header.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  if (badge)  { badge.style.display = open ? 'none' : ''; badge.textContent = scenarios.length || '10'; }
  if (label)  { label.style.display = open ? '' : 'none'; }

  if (body) {
    if (open && scenarios.length > 0) {
      body.innerHTML = `<div style="display:grid;gap:8px;">
        ${scenarios.map(s => {
          const card = buildScenarioCardData(s);
          return `<button class="scenario-card" data-scenario-id="${card.id}"
            style="border-left-color:${card.color}">
            <div class="city-label" style="color:${card.color}">${esc(card.city)}</div>
            <div class="zone-label">${esc(card.zone)}</div>
            <div class="type-label">${esc(card.type)}</div>
          </button>`;
        }).join('')}
      </div>`;
    } else if (open && scenarios.length === 0) {
      body.innerHTML = `<div style="padding:12px;font-size:12px;color:var(--mute);">
        Scenari non disponibili (backend offline).
      </div>`;
    } else {
      body.innerHTML = '';
    }
  }
}

// ── LOADING state ─────────────────────────────────────────────────────────────
let _loadingInterval = null;
let _loadingStep     = 0;

function renderLoadingOverlay(zona) {
  const zonaEl  = $('loading-zona');
  const stepsEl = $('loading-steps');
  if (zonaEl) zonaEl.textContent = `Analizzando ${zona}`;

  _loadingStep = 0;
  function drawSteps() {
    if (!stepsEl) return;
    stepsEl.innerHTML = LOADING_STEPS.map((s, i) => {
      const done    = i < _loadingStep;
      const current = i === _loadingStep;
      return `<div style="display:flex;gap:10px;align-items:center;font-size:12.5px;">
        <span style="width:18px;height:18px;border-radius:50%;flex-shrink:0;
          background:${done ? 'var(--teal)' : '#e6e3da'};
          border:${done ? 'none' : '1.5px dashed var(--mute)'};
          color:#fff;display:flex;align-items:center;justify-content:center;
          font-size:10px;font-weight:700;">${done ? '✓' : (current ? '⋯' : '')}</span>
        <span style="color:${done ? 'var(--ink)' : 'var(--mute)'}">${s}</span>
      </div>`;
    }).join('');
  }
  drawSteps();
  _loadingInterval = setInterval(() => {
    _loadingStep = Math.min(_loadingStep + 1, LOADING_STEPS.length);
    drawSteps();
  }, 360);
}

function clearLoadingInterval() {
  if (_loadingInterval) { clearInterval(_loadingInterval); _loadingInterval = null; }
}

// ── RESULTS / FILTER state ────────────────────────────────────────────────────
function renderPOIPanel(state) {
  const panel      = $('panel-poi');
  const titleEl    = $('panel-poi-title');
  const body       = $('panel-poi-body');
  const filterBar  = $('filter-bar');
  const headerEl   = $('panel-poi-header');
  if (!panel || !state.data) return;

  const pois     = state.data.poi || [];
  const filter   = state.filter;
  const open     = state.poiPanelOpen !== false;
  const selected = state.selectedPoiId;

  if (titleEl) titleEl.textContent = state.data.zona_normalizzata || '';
  if (headerEl) {
    headerEl.querySelector('.toggle-arrow').textContent = open ? '▾' : '▸';
    headerEl.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  // Filter bar
  if (filterBar) {
    if (filter) {
      const hidden = pois.filter(p => p.confidence !== filter).length;
      filterBar.style.display = '';
      filterBar.innerHTML = `<span>Filtro:</span>${confBadgeHTML(filter, true)}
        <span style="flex:1"></span>
        <span style="font-size:10px;color:var(--mute)">${hidden} nascosti</span>`;
    } else {
      filterBar.style.display = 'none';
    }
  }

  if (body) {
    if (open) {
      const visible  = filterVisiblePOIs(pois, filter);
      const visCount = visible.length;
      const eyebrow  = filter
        ? `POI visibili · ${visCount} / ${pois.length}`
        : `POI identificati · ${pois.length}`;
      body.innerHTML = `
        <div style="padding:6px 13px;border-bottom:1px solid var(--hair);background:var(--white);flex-shrink:0;">
          <span class="eyebrow">${eyebrow}</span>
        </div>
        ${pois.map(p => {
          const dim    = Boolean(filter && p.confidence !== filter);
          const active = state.screen === STATES.DETAIL && selected === p.id;
          return `<div class="poi-row${active ? ' active' : ''}${dim ? ' dim' : ''}"
            data-poi-id="${p.id}" role="option" tabindex="0"
            aria-label="${esc(p.name)}" aria-selected="${active}">
            <div class="poi-row-top">
              ${dotPinHTML(p.id, p.confidence, { dim })}
              <span class="poi-name">${esc(p.name)}</span>
              ${confBadgeHTML(p.confidence, true)}
            </div>
            <div class="poi-class">risk:${esc(p.terminus_class)}</div>
          </div>`;
        }).join('')}
      `;
    } else {
      body.innerHTML = '';
    }
  }
}

// ── DETAIL state (Stato C) ───────────────────────────────────────────────────
function renderDetailPanel(state) {
  const panel = $('panel-detail');
  if (!panel || !state.data || !state.selectedPoiId) return;

  const poi = (state.data.poi || []).find(p => p.id === state.selectedPoiId);
  if (!poi) return;

  // Use pure helper: splits sparql_path + groups risks by tag (no inline logic here).
  const { sparqlParts: pathParts, groups } = buildDetailModel(poi, state.data.risk_models || []);

  panel.innerHTML = `
    <div class="panel-header" style="cursor:default;gap:11px;">
      ${dotPinHTML(poi.id, poi.confidence, { lg: true })}
      <div style="flex:1;min-width:0;">
        <div style="font-size:17px;font-weight:700;line-height:1.15;">${esc(poi.name)}</div>
        <span style="font-family:var(--font-mono);font-size:11px;color:var(--mute);">
          risk:${esc(poi.terminus_class)}
        </span>
      </div>
      ${confBadgeHTML(poi.confidence)}
      <button id="btn-close-detail"
        style="cursor:pointer;color:var(--mute);font-size:18px;padding:0 4px;
               line-height:1;background:none;border:none;flex-shrink:0;"
        aria-label="Chiudi dettaglio POI">✕</button>
    </div>
    <div class="panel-body" style="padding:16px;display:flex;flex-direction:column;gap:16px;">
      <div>
        <div class="eyebrow" style="margin-bottom:9px;">Citazioni ontologia · path SPARQL</div>
        ${pathParts.length
          ? `<div class="citation-row">
              ${pathParts.map((part, i) => {
                if (i === 0) return `<span class="citation-cls">${esc(part)}</span>`;
                return `<span class="citation-arrow">→</span>
                  <span style="color:${i === pathParts.length - 1 ? 'var(--ink)' : 'var(--ink2)'}">${esc(part)}</span>`;
              }).join('')}
              ${confBadgeHTML(poi.confidence, true)}
            </div>`
          : `<span style="font-size:11px;color:var(--mute)">Nessun path disponibile</span>`}
      </div>
      <div>
        <div class="eyebrow" style="margin-bottom:11px;">Fattori di rischio · per fonte</div>
        <div style="display:flex;flex-direction:column;gap:13px;">
          ${['ONTOLOGIA', 'CONTESTO', 'SPECULATIVO']
            .filter(tag => groups[tag]?.length)
            .map(tag => `
              <div>
                <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:8px;
                  border-bottom:2px solid ${srcBorderColor(tag)};padding-bottom:6px;">
                  ${srcTagHTML(tag)}
                  <span style="font-size:10.5px;color:var(--mute);font-style:italic;">${SRC_DESC[tag]}</span>
                </div>
                <div style="display:flex;flex-direction:column;gap:8px;">
                  ${groups[tag].map(r => `
                    <div style="display:flex;gap:9px;align-items:flex-start;font-size:12.5px;line-height:1.5;">
                      ${confBadgeHTML((r.confidence || '').toLowerCase(), true)}
                      <span style="flex:1">${esc(r.hazard)}</span>
                    </div>`).join('')}
                </div>
              </div>`).join('')}
        </div>
      </div>
    </div>
    <div style="padding:12px 16px;border-top:1.5px solid var(--ink);
      background:var(--white);display:flex;gap:9px;flex-shrink:0;">
      <button class="btn sm"
        style="flex:1;justify-content:center;border-color:var(--conf-plausibile-color);
               color:var(--conf-plausibile-color);">⚐ Segnala errore</button>
      <button class="btn sm" style="flex:1;justify-content:center;">⤓ Esporta scheda</button>
    </div>
  `;
}

// ── NARRATIVE bottom-sheet ────────────────────────────────────────────────────
function renderNarrativeSheet(state) {
  const panel   = $('panel-narrative');
  const headerEl= $('panel-narrative-header');
  const body    = $('panel-narrative-body');
  const titleEl = $('narrative-title');
  if (!panel || !state.data) return;

  const open = state.narrOpen !== false;
  panel.classList.toggle('collapsed', !open);
  if (headerEl) {
    headerEl.querySelector('.toggle-arrow').textContent = open ? '▾' : '▸';
    headerEl.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  if (titleEl) {
    titleEl.textContent = `◇ Narrativa generata — ${state.data.città || ''} · ${state.data.zona_normalizzata || ''}`;
  }

  if (body && open) {
    // Build narrative sections from risk_models tags — no backend `narrative_sections` field.
    // Spec-frontend §B (bottom-sheet): sezioni per fonte da [ONTOLOGIA]/[CONTESTO]/[SPECULATIVO].
    const sections = buildNarrativeSections(state.data.risk_models || []);
    body.innerHTML = `
      <div style="font-size:14px;line-height:1.6;color:var(--ink);max-width:960px;">
        ${esc(state.data.narrativa || '')}
      </div>
      ${sections.length ? `
        <div style="display:grid;grid-template-columns:repeat(${sections.length},1fr);
          border:1.5px solid var(--ink);border-radius:6px;overflow:hidden;">
          ${sections.map((s, i) => `
            <div style="padding:12px 15px;
              ${i ? 'border-left:1px solid var(--hair);' : ''}
              background:${i % 2 ? 'transparent' : 'rgba(0,0,0,0.012)'}">
              <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:8px;
                border-bottom:2px solid ${srcBorderColor(s.tag)};padding-bottom:7px;">
                ${srcTagHTML(s.tag)}
                <span style="font-size:10.5px;color:var(--mute);font-style:italic;">${SRC_DESC[s.tag] || ''}</span>
              </div>
              <ul style="margin:0;padding-left:16px;display:flex;flex-direction:column;gap:4px;">
                ${s.hazards.map(h => `<li style="font-size:12.5px;line-height:1.65;color:var(--ink);">${esc(h)}</li>`).join('')}
              </ul>
            </div>`).join('')}
        </div>` : ''}
    `;
  }
}

// ── BASE state ────────────────────────────────────────────────────────────────
function renderBasePanel(state) {
  const headerEl  = $('base-header');
  const tbody     = $('base-table-body');
  const filtersEl = $('base-filters');
  if (!state.data) return;

  const data = state.data;
  if (headerEl) {
    headerEl.innerHTML = `<b style="color:var(--ink)">${(data.poi || []).length} risultati</b> — Tutti i tipi · ${esc(data.città || '')} · ${esc(data.zona_normalizzata || '')}`;
  }

  // Flatten: poi × risk
  const rows = [];
  (data.poi || []).forEach(poi => {
    const model = (data.risk_models || []).find(r => r.poi === poi.name);
    (model?.risks || []).forEach(r => {
      rows.push({ poi: poi.name, hazard: r.hazard, cat: poi.terminus_class });
    });
  });

  if (tbody) {
    tbody.innerHTML = rows.map((r, i) => `
      <tr style="background:${i % 2 ? '#fafaf7' : '#fff'}">
        <td style="padding:10px 16px;border-right:1px solid var(--hair)">${esc(r.poi)}</td>
        <td style="padding:10px 16px;color:var(--ink2);border-right:1px solid var(--hair)">${esc(r.hazard)}</td>
        <td style="padding:10px 16px;font-family:var(--font-mono);font-size:11px;color:var(--mute)">${esc(r.cat)}</td>
      </tr>`).join('');
  }

  if (filtersEl) {
    filtersEl.innerHTML = ['Tipo POI', 'Città', 'Zona'].map(l => `
      <div>
        <div style="font-size:11px;color:var(--ink2);margin-bottom:3px;">${l}</div>
        <div style="border:1px solid var(--border-mid);border-radius:3px;padding:7px 9px;font-size:12px;
          color:var(--mute);background:#fff;display:flex;justify-content:space-between;">
          <span>Seleziona…</span><span style="font-size:9px">▼</span>
        </div>
      </div>`).join('') +
      /* TODO(B2): wire to analyzeBaseline() when /analyze/baseline is available (backend #16).
         Currently dispatches BASELINE_SEARCH; app.js handles it with analyzeBaseline(). */
      `<button id="btn-base-search" data-action="base-search"
        style="border:1px solid var(--ink2);border-radius:3px;padding:7px;text-align:center;
        font-size:13px;font-weight:600;background:#fff;cursor:pointer;margin-top:3px;width:100%;">
        Cerca
      </button>`;
  }
}

// ── Main render function ───────────────────────────────────────────────────────
/**
 * Idempotent render: call on every state change.
 * @param {AppState} state
 * @param {{ scenarios?: Array }} [opts]
 */
export function render(state, { scenarios = [] } = {}) {
  clearLoadingInterval();
  renderHeaderRight(state);

  switch (state.screen) {
    case STATES.INPUT:
    case STATES.ERROR:
      showOnly('panel-input', 'panel-scenarios');
      renderInputPanel(state);
      renderScenariosPanel(state, scenarios);
      break;

    case STATES.LOADING:
      showOnly('overlay-loading');
      renderLoadingOverlay(state.pendingZona || 'la zona');
      break;

    case STATES.RESULTS:
    case STATES.FILTER: {
      showOnly('panel-poi', 'panel-narrative', 'map-hint');
      renderPOIPanel(state);
      renderNarrativeSheet(state);
      const hint = $('map-hint');
      if (hint) {
        hint.textContent = state.filter
          ? `filtro attivo: solo ${CONF[state.filter]?.label}`
          : 'clic marker o card → dettaglio POI';
      }
      break;
    }

    case STATES.DETAIL:
      showOnly('panel-poi', 'panel-detail', 'panel-narrative', 'map-hint');
      renderPOIPanel(state);
      renderDetailPanel(state);
      renderNarrativeSheet(state);
      // Focus detail panel for keyboard/screen-reader users
      setTimeout(() => { const el = $('panel-detail'); if (el) el.focus?.(); }, 60);
      break;

    case STATES.BASE:
      showOnly('panel-base');
      renderBasePanel(state);
      break;
  }
}

/**
 * Scrolls the POI row card for the given id into view inside the POI panel.
 * Called by app.js after SELECT_POI so that a marker click auto-scrolls the list.
 * No-op if the element is not found or already visible.
 * @param {string} poiId
 */
export function scrollPoiCardIntoView(poiId) {
  const row = document.querySelector(`[data-poi-id="${poiId}"]`);
  if (!row) return;
  row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// ── Tiny XSS guard ────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
