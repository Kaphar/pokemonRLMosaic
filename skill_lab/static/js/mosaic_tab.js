import { el, state } from './state.js';
import { isMosaicTabActive } from './util.js';

function updateMosaic() {
  fetch('/api/mosaic', { cache: 'no-store' })
    .then(function(r) {
      if (r.status === 204) {
        el.mosaicStatus.textContent = 'no stream';
        if (state.mosaicObjectUrl) {
          URL.revokeObjectURL(state.mosaicObjectUrl);
          state.mosaicObjectUrl = null;
        }
        el.mosaicImage.removeAttribute('src');
        return null;
      }
      return r.blob();
    })
    .then(function(blob) {
      if (!blob) return;
      if (state.mosaicObjectUrl) {
        URL.revokeObjectURL(state.mosaicObjectUrl);
      }
      state.mosaicObjectUrl = URL.createObjectURL(blob);
      el.mosaicImage.src = state.mosaicObjectUrl;
      el.mosaicStatus.textContent = 'live';
    })
    .catch(function() {
      el.mosaicStatus.textContent = 'offline';
    });
}

function initMosaic() {
  el.mosaicImage.addEventListener('error', function() {
    el.mosaicStatus.textContent = 'offline';
  });
}

export { updateMosaic, initMosaic };
