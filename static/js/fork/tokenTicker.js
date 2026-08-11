// ============================================
// Fork module: live token ticker beside the model picker
// This file is fork-owned. Upstream does not change it (doc 021).
// Comments follow ASD-STE100.
// ============================================

const el = (id) => document.getElementById(id);

// The ticker watches the chat transcript with a MutationObserver. It
// does not touch the stream code in chat.js. It counts new text and
// shows an estimate of tokens each second. One token is near four
// characters. The tilde in the label shows that this is an estimate.

const TICK_MS = 500;        // refresh period for the display
const WINDOW_MS = 2000;     // sliding window for the rate
const IDLE_HIDE_MS = 3000;  // hide the ticker after this quiet time
const CHARS_PER_TOKEN = 4;  // coarse estimate, good for a ticker

function init() {
  const ticker = el('fork-tps');
  const history = el('chat-history');
  if (!ticker || !history) return;

  let samples = [];          // [time_ms, chars_added]
  let lastGrowth = 0;

  const observer = new MutationObserver((mutations) => {
    let added = 0;
    for (const m of mutations) {
      if (m.type === 'characterData') {
        added += Math.max(0, (m.target.data || '').length - (m.oldValue || '').length);
      } else if (m.type === 'childList') {
        for (const node of m.addedNodes) {
          added += (node.textContent || '').length;
        }
      }
    }
    if (added > 0) {
      const now = performance.now();
      samples.push([now, added]);
      lastGrowth = now;
    }
  });
  observer.observe(history, {
    subtree: true,
    childList: true,
    characterData: true,
    characterDataOldValue: true,
  });

  setInterval(() => {
    const now = performance.now();
    samples = samples.filter(([t]) => now - t <= WINDOW_MS);
    if (now - lastGrowth > IDLE_HIDE_MS || samples.length === 0) {
      ticker.hidden = true;
      return;
    }
    const chars = samples.reduce((sum, [, c]) => sum + c, 0);
    const seconds = Math.max(0.001, Math.min(WINDOW_MS, now - samples[0][0]) / 1000);
    const tps = chars / CHARS_PER_TOKEN / seconds;
    ticker.textContent = '≈ ' + tps.toFixed(1) + ' t/s';
    ticker.hidden = false;
  }, TICK_MS);
}

export default { init };
