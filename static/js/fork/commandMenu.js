// ============================================
// Fork module: command menu (model controls popup)
// This file is fork-owned. Upstream does not change it (doc 021).
// Controls: effort stepper, thinking switch, verifier switch.
// Comments follow ASD-STE100.
// ============================================
import uiModule from '../ui.js';

const el = (id) => document.getElementById(id);

const THINK_KEY = 'odysseus-think-mode';
const EFFORT_KEY = 'odysseus-reasoning-effort';
const EFFORT_STATES = ['default', 'low', 'medium', 'high'];

// The send path in chat.js reads the two localStorage keys above and
// adds them to each request. Keep the key names equal in both files.

function init() {
  const cmdBtn = el('cmd-menu-btn'), cmdMenu = el('cmd-menu');
  const thinkCheck = el('cmd-think-check');
  const stepper = el('cmd-effort-stepper'), effortState = el('cmd-effort-state');
  const verCheck = el('cmd-verifier-check');
  if (!cmdBtn || !cmdMenu || !thinkCheck || !stepper || !verCheck) return;

  // Same technique as the + overflow menu: move the popup to <body>
  // to escape the composer's container-type trap, then set fixed
  // coordinates from the chip. The composer's containment makes fixed
  // positioning useless inside it — this mirrors the working menu.
  const place = () => {
    const r = cmdBtn.getBoundingClientRect();
    cmdMenu.style.left = r.left + 'px';
    cmdMenu.style.maxHeight = '';
    cmdMenu.style.overflowY = '';
    const avail = r.top - 16;
    const natural = cmdMenu.scrollHeight;
    const h = Math.min(natural, avail);
    if (natural > avail) {
      cmdMenu.style.maxHeight = avail + 'px';
      cmdMenu.style.overflowY = 'auto';
    }
    cmdMenu.style.top = (r.top - 8 - h) + 'px';
    cmdMenu.style.bottom = 'auto';
  };

  // Open and close the popup. A click on a control does not close it.
  cmdBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (cmdMenu.classList.contains('hidden')) {
      document.body.appendChild(cmdMenu);
      cmdMenu.classList.remove('hidden');
      place();
    } else {
      cmdMenu.classList.add('hidden');
    }
  });
  // A resize moves the chip. Close the popup instead of drifting.
  window.addEventListener('resize', () => cmdMenu.classList.add('hidden'));
  document.addEventListener('click', (e) => {
    if (!cmdMenu.classList.contains('hidden') && !cmdMenu.contains(e.target) && !cmdBtn.contains(e.target)) {
      cmdMenu.classList.add('hidden');
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') cmdMenu.classList.add('hidden');
  });

  const steps = Array.from(stepper.querySelectorAll('.cmd-step'));
  const _cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

  const renderLocal = () => {
    // Thinking switch: on = the model can think, off = no thinking.
    // A stored legacy value 'on' counts as on.
    thinkCheck.checked = (localStorage.getItem(THINK_KEY) || 'auto') !== 'off';
    const eff = localStorage.getItem(EFFORT_KEY) || 'default';
    effortState.textContent = '(' + _cap(eff) + ')';
    const idx = Math.max(0, EFFORT_STATES.indexOf(eff));
    steps.forEach((s, i) => s.classList.toggle('active', i === idx));
  };
  renderLocal();

  thinkCheck.addEventListener('change', () => {
    localStorage.setItem(THINK_KEY, thinkCheck.checked ? 'auto' : 'off');
  });

  // Effort stepper: tap a stop, or move across the stops. The position
  // goes to the nearest stop. The state changes only at a stop. The
  // render only changes CSS classes. Nothing moves against the pointer.
  const setEffort = (idx) => {
    const clamped = Math.min(EFFORT_STATES.length - 1, Math.max(0, idx));
    if ((localStorage.getItem(EFFORT_KEY) || 'default') !== EFFORT_STATES[clamped]) {
      localStorage.setItem(EFFORT_KEY, EFFORT_STATES[clamped]);
      renderLocal();
    }
  };
  steps.forEach((s, i) => s.addEventListener('click', () => setEffort(i)));
  const idxFromEvent = (e) => {
    const r = stepper.getBoundingClientRect();
    const frac = (e.clientX - r.left) / Math.max(1, r.width);
    return Math.round(frac * (EFFORT_STATES.length - 1));
  };
  stepper.addEventListener('pointerdown', (e) => {
    try { stepper.setPointerCapture(e.pointerId); } catch (_) {}
    setEffort(idxFromEvent(e));
  });
  stepper.addEventListener('pointermove', (e) => {
    if (e.buttons) setEffort(idxFromEvent(e));
  });

  // Read the saved verifier state. If the read fails, say so. A
  // silent failure here showed a wrong switch state for days
  // (doc 021, phase 1).
  const refreshVerifier = async () => {
    try {
      const r = await fetch('/api/auth/settings', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const s = await r.json();
      verCheck.checked = !!s.agent_verifier_subagent;
    } catch (err) {
      console.warn('verifier state read failed:', err);
      uiModule.showError && uiModule.showError('Could not read the verifier setting');
    }
  };
  refreshVerifier();

  // Save the new verifier state. If the save fails, put the switch
  // back and show the reason.
  verCheck.addEventListener('change', async () => {
    const want = verCheck.checked;
    let reason = '';
    try {
      const r = await fetch('/api/auth/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ agent_verifier_subagent: want }),
      });
      if (r.ok) return;
      reason = 'HTTP ' + r.status;
      try { reason = (await r.json()).detail || reason; } catch (_) {}
    } catch (err) {
      reason = String(err);
    }
    verCheck.checked = !want;
    uiModule.showError && uiModule.showError('Verifier setting not saved: ' + reason);
  });
}

export default { init };
