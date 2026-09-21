import { el, state } from './state.js';
import { isDynamicMosaicTabActive } from './util.js';
import { selectInspectorEnv } from './inspector_tab.js';

function updateDynamicMosaic(envCount) {
  const grid = el.dynamicMosaicGrid;
  if (!grid) return;

  const maxPage = Math.max(0, Math.ceil(envCount / state.dynamicMosaicPageSizeVal) - 1);
  if (state.dynamicMosaicCurrentPage > maxPage) {
    state.dynamicMosaicCurrentPage = maxPage;
  }
  const startIndex = state.dynamicMosaicCurrentPage * state.dynamicMosaicPageSizeVal;
  const endIndex = Math.min(startIndex + state.dynamicMosaicPageSizeVal, envCount);
  const visibleCount = endIndex - startIndex;

  el.dynamicMosaicPageIndicator.textContent = 'Page ' + (state.dynamicMosaicCurrentPage + 1) + ' of ' + (maxPage + 1);

  const currentCells = grid.querySelectorAll('.dynamic-mosaic-cell');
  if (currentCells.length !== visibleCount) {
    grid.innerHTML = '';
    for (let i = startIndex; i < endIndex; i++) {
      const cell = document.createElement('div');
      cell.className = 'dynamic-mosaic-cell';
      cell.onclick = (function(idx) {
        return function() {
          selectInspectorEnv(idx);
        };
      })(i);

      const img = document.createElement('img');
      img.id = 'dynamic-frame-' + i;
      img.alt = 'Env ' + (i + 1);
      img.addEventListener('error', function() {
        this.style.opacity = '0.3';
      });

      const label = document.createElement('div');
      label.style.cssText = 'position: absolute; top: 4px; left: 4px; background: rgba(15, 22, 34, 0.85); padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; color: var(--accent); font-weight: 600;';
      label.textContent = 'E' + (i + 1);

      cell.appendChild(img);
      cell.appendChild(label);
      grid.appendChild(cell);
    }
  }

  for (let i = startIndex; i < endIndex; i++) {
    const img = document.getElementById('dynamic-frame-' + i);
    if (img) {
      const newUrl = '/api/individual/' + i + '?t=' + Date.now();
      img.src = newUrl;
    }
  }
  el.dynamicMosaicStatus.textContent = 'live (' + envCount + ' streams, showing ' + visibleCount + ')';
}

function calculateBandwidth() {
  const now = Date.now();
  const timeDiff = (now - state.lastBandwidthTime) / 1000;
  if (timeDiff < 1) return;

  const visibleEnvs = parseInt(el.dynamicMosaicPageSize.value, 10);
  const isLive = el.dynamicMosaicLiveUpdate.checked;
  if (!isLive) {
    el.dynamicMosaicBandwidth.textContent = 'Bandwidth: Paused';
    return;
  }

  const estimatedBytesPerFrame = 12000;
  const framesPerSecond = 5;
  const totalBytesPerSecond = visibleEnvs * estimatedBytesPerFrame * framesPerSecond;

  let bandwidthStr;
  if (totalBytesPerSecond > 1000000) {
    bandwidthStr = (totalBytesPerSecond / 1000000).toFixed(2) + ' MB/s';
  } else if (totalBytesPerSecond > 1000) {
    bandwidthStr = (totalBytesPerSecond / 1000).toFixed(2) + ' KB/s';
  } else {
    bandwidthStr = totalBytesPerSecond.toFixed(0) + ' B/s';
  }
  el.dynamicMosaicBandwidth.textContent = 'Bandwidth: ~' + bandwidthStr;
  state.lastBandwidthTime = now;
}

function initDynamicMosaic() {
  el.dynamicMosaicPageSize.addEventListener('input', function() {
    state.dynamicMosaicPageSizeVal = parseInt(this.value, 10);
    el.dynamicMosaicPageSizeValue.textContent = state.dynamicMosaicPageSizeVal.toString();
    state.dynamicMosaicCurrentPage = 0;
    if (isDynamicMosaicTabActive()) {
      const envCount = state.lastState.envs ? state.lastState.envs.length : 0;
      if (envCount > 0) {
        updateDynamicMosaic(envCount);
      }
    }
  });

  el.dynamicMosaicPrevBtn.addEventListener('click', function() {
    if (state.dynamicMosaicCurrentPage > 0) {
      state.dynamicMosaicCurrentPage--;
      if (isDynamicMosaicTabActive()) {
        const envCount = state.lastState.envs ? state.lastState.envs.length : 0;
        if (envCount > 0) {
          updateDynamicMosaic(envCount);
        }
      }
    }
  });

  el.dynamicMosaicNextBtn.addEventListener('click', function() {
    const envCount = state.lastState.envs ? state.lastState.envs.length : 0;
    const maxPage = Math.max(0, Math.ceil(envCount / state.dynamicMosaicPageSizeVal) - 1);
    if (state.dynamicMosaicCurrentPage < maxPage) {
      state.dynamicMosaicCurrentPage++;
      if (isDynamicMosaicTabActive()) {
        const envCount = state.lastState.envs ? state.lastState.envs.length : 0;
        if (envCount > 0) {
          updateDynamicMosaic(envCount);
        }
      }
    }
  });
}

export { updateDynamicMosaic, calculateBandwidth, initDynamicMosaic };
