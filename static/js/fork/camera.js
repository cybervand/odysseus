// ============================================
// Fork module: camera capture from the chat overflow menu
// This file is fork-owned. Upstream does not change it (doc 021).
// Comments follow ASD-STE100.
// ============================================
import fileHandlerModule from '../fileHandler.js';

const el = (id) => document.getElementById(id);

// Phones open the camera application through the input's accept and
// capture attributes. Desktops show an image picker. The photo becomes
// a normal attachment.
function init() {
  const cameraBtn = el('overflow-camera-btn');
  const cameraInput = el('camera-input');
  if (!cameraBtn || !cameraInput) return;

  cameraBtn.addEventListener('click', () => cameraInput.click());
  cameraInput.addEventListener('change', async (e) => {
    await fileHandlerModule.addFiles(Array.from(e.target.files || []));
    e.target.value = '';
    // Put the focus back in the message box after the camera closes.
    const ta = el('message');
    if (ta) setTimeout(() => ta.focus(), 100);
  });
}

export default { init };
