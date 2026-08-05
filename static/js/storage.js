// static/js/storage.js
// Centralized localStorage access with key constants and JSON parse safety

// ── Key constants ──
export const KEYS = {
  THEME: 'odysseus-theme',
  TOGGLES: 'odysseus-toggles',
  SIDEBAR_COLLAPSED: 'sidebar-collapsed',
  SIDEBAR_WIDTH: 'sidebar-width',
  SIDEBAR_SIDE: 'sidebar-side',
  CURRENT_SESSION: 'currentSessionId',
  COMPARE_SAVE: 'compare-save-results',
  COMPARE_CHAT: 'compare-continue-chat',
  COMPARE_BLIND: 'compare-blind',
  COMPARE_RANDOM: 'compare-randomize',
  MODELS_EXPANDED: 'odysseus-model-expanded',
  MODEL_ENDPOINTS: 'odysseus-model-endpoints',
  MODEL_SELECTED: 'odysseus-selected-model',
  SORT_ORDER: 'odysseus-sessions-sort',
  CHAT_SEARCH_SCOPE: 'odysseus-search-scope',
  INCOGNITO: 'odysseus-incognito',
  RAG_ACTIVE: 'odysseus-rag-active',
  MCP_ACTIVE: 'odysseus-mcp-active',
  SECTION_ORDER: 'sidebar-section-order',
  ADMIN_LAST_TAB: 'admin-last-tab',
  DENSITY: 'odysseus-density',
  UI_SCALE: 'odysseus-ui-scale',
  WORKSPACE: 'odysseus-workspace',
  SESSION_TOOLS: 'odysseus-session-tools'
};

/**
 * Safely get and parse a JSON value from localStorage.
 * Returns fallback on any error.
 */
export function getJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback !== undefined ? fallback : null;
    return JSON.parse(raw);
  } catch (e) {
    console.warn('[Storage] Failed to parse key "' + key + '":', e.message);
    return fallback !== undefined ? fallback : null;
  }
}

/**
 * Set a JSON-serialized value in localStorage.
 */
export function setJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    console.warn('[Storage] Failed to set key "' + key + '":', e.message);
  }
}

/**
 * Get a raw string value from localStorage.
 */
export function get(key, fallback) {
  try {
    const val = localStorage.getItem(key);
    return val !== null ? val : (fallback !== undefined ? fallback : null);
  } catch (e) {
    return fallback !== undefined ? fallback : null;
  }
}

/**
 * Set a raw string value in localStorage.
 */
export function set(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (e) {
    console.warn('[Storage] Failed to set key "' + key + '":', e.message);
  }
}

/**
 * Remove a key from localStorage.
 */
export function remove(key) {
  try {
    localStorage.removeItem(key);
  } catch (e) {
    // Ignore removal errors
  }
}

// ── Toggle state helpers ──

export function loadToggleState() {
  return getJSON(KEYS.TOGGLES, {});
}

export function saveToggleState(state) {
  setJSON(KEYS.TOGGLES, state);
}

export function getToggle(name, fallback) {
  const state = loadToggleState();
  return state[name] !== undefined ? state[name] : (fallback !== undefined ? fallback : false);
}

// ── Per-session tool preferences (tri-state) ──
// A toggle choice made while a session is open is stored FOR THAT SESSION.
// getSessionToolPref returns true/false only when the user explicitly chose
// for this session, undefined otherwise — the caller must OMIT the request
// field on undefined so the server's own defaults decide. This is what stops
// the browser's global defaults from clobbering API-created sessions.
const SESSION_TOOLS_MAX = 100;

export function getSessionToolPref(sessionId, key) {
  if (!sessionId) return undefined;
  const all = getJSON(KEYS.SESSION_TOOLS, {});
  const entry = all[sessionId];
  return entry && Object.prototype.hasOwnProperty.call(entry, key) ? !!entry[key] : undefined;
}

export function setSessionToolPref(sessionId, key, value) {
  if (!sessionId) return;
  const all = getJSON(KEYS.SESSION_TOOLS, {});
  const entry = all[sessionId] || {};
  entry[key] = !!value;
  entry._t = Date.now();
  all[sessionId] = entry;
  // LRU cap so the map can't grow unboundedly across hundreds of sessions.
  const ids = Object.keys(all);
  if (ids.length > SESSION_TOOLS_MAX) {
    ids.sort((a, b) => (all[a]._t || 0) - (all[b]._t || 0));
    for (const id of ids.slice(0, ids.length - SESSION_TOOLS_MAX)) delete all[id];
  }
  setJSON(KEYS.SESSION_TOOLS, all);
}

export function setToggle(name, value) {
  const state = loadToggleState();
  state[name] = value;
  saveToggleState(state);
}

const Storage = {
  KEYS,
  getJSON,
  setJSON,
  get,
  set,
  remove,
  loadToggleState,
  saveToggleState,
  getToggle,
  setToggle,
  getSessionToolPref,
  setSessionToolPref
};

export default Storage;
