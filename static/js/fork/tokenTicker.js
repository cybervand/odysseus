// ============================================
// Fork module: live token ticker beside the model picker
// This file is fork-owned. Upstream does not change it (doc 021).
// Comments follow ASD-STE100.
// ============================================

const el = (id) => document.getElementById(id);

// The ticker measures the total text length of the transcript on each
// tick and counts only growth. The first version counted DOM
// mutations, and the markdown renderer repaints the full message on
// each chunk — the same text got counted many times and the display
// showed thousands of tokens each second (seen 2026-08-12). A repaint
// does not change the total length, so the delta method is immune.
// One token is near four characters. The tilde shows the estimate.

const TICK_MS = 500;        // refresh period for the display
const WINDOW_MS = 2000;     // sliding window for the rate
const IDLE_HIDE_MS = 3000;  // hide the ticker after this quiet time
const CHARS_PER_TOKEN = 4;  // coarse estimate, good for a ticker

function init() {
  const ticker = el('fork-tps');
  const history = el('chat-history');
  if (!ticker || !history) return;

  let lastLen = null;
  let lastGrowth = 0;
  let samples = [];  // [time_ms, chars_added]

  setInterval(() => {
    const now = performance.now();
    const len = (history.textContent || '').length;
    if (lastLen === null) {
      lastLen = len;
      return;
    }
    const added = Math.max(0, len - lastLen);
    lastLen = len;
    if (added > 0) {
      samples.push([now, added]);
      lastGrowth = now;
    }
    samples = samples.filter(([t]) => now - t <= WINDOW_MS);
    if (now - lastGrowth > IDLE_HIDE_MS || samples.length === 0) {
      ticker.hidden = true;
      return;
    }
    const chars = samples.reduce((sum, [, c]) => sum + c, 0);
    const seconds = (now - samples[0][0] + TICK_MS) / 1000;
    const tps = chars / CHARS_PER_TOKEN / seconds;
    ticker.textContent = '≈ ' + tps.toFixed(1) + ' t/s';
    ticker.hidden = false;
  }, TICK_MS);
}

export default { init };
