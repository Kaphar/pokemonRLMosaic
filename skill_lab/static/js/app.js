import { el, state } from './state.js';
import { isMosaicTabActive, isInspectorTabActive, isDynamicMosaicTabActive } from './util.js';
import { renderMap, renderStats, initMap, updateLavaToggle } from './map_tab.js';
import { updateMosaic, initMosaic } from './mosaic_tab.js';
import { updateDynamicMosaic, calculateBandwidth, initDynamicMosaic } from './dynamic_mosaic.js';
import {
  initInspector,
  updateInspectorSelect,
  fetchInspectorData,
  updateInspectorScreen,
  selectInspectorEnv,
  fetchControlState,
} from './inspector_tab.js';
import { initConfig, initControlBindings } from './config_tab.js';

function setStreaming(payload) {
  fetch('/api/streaming', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(function() {});
}

function update() {
  fetch('/api/state', { cache: 'no-store' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data || !Array.isArray(data.envs)) return;
      el.status.textContent = 'live';
      renderMap(data);
      renderStats(data);
      updateInspectorSelect(data.envs);
    })
    .catch(function() {
      el.status.textContent = 'offline';
    });

  if (isMosaicTabActive()) {
    updateMosaic();
  }
  if (isInspectorTabActive()) {
    fetchInspectorData();
  }
}

function initTabs() {
  el.tabBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      const target = btn.getAttribute('data-tab');

      const wasMosaicActive = isMosaicTabActive();
      const wasDynamicActive = isDynamicMosaicTabActive();

      el.tabBtns.forEach(function(b) { b.classList.remove('active'); });
      el.tabPanes.forEach(function(p) { p.classList.remove('active'); });
      btn.classList.add('active');
      document.getElementById(target).classList.add('active');

      if (!wasMosaicActive && target === 'mosaic-tab') {
        setStreaming({ mosaic: true });
      }
      if (wasMosaicActive && target !== 'mosaic-tab') {
        setStreaming({ mosaic: false });
      }
      if (!wasDynamicActive && target === 'dynamic-mosaic-tab') {
        setStreaming({ individual_frames: true });
      }
      if (wasDynamicActive && target !== 'dynamic-mosaic-tab') {
        setStreaming({ individual_frames: false });
      }

      if (target === 'mosaic-tab') {
        updateMosaic();
      }
      if (target === 'inspector-tab') {
        updateInspectorScreen();
        fetchInspectorData();
        fetchControlState();
      }
    });
  });
}

let dynamicMosaicTimerId = null;

function scheduleDynamicMosaic() {
  if (dynamicMosaicTimerId !== null) {
    clearTimeout(dynamicMosaicTimerId);
    dynamicMosaicTimerId = null;
  }
  const delay = parseInt(el.dynamicMosaicPoll?.value || '200', 10);
  dynamicMosaicTimerId = setTimeout(function tick() {
    const dmTab = document.getElementById('dynamic-mosaic-tab');
    if (dmTab && dmTab.classList.contains('active') && el.dynamicMosaicLiveUpdate) {
      const isLive = el.dynamicMosaicLiveUpdate.checked;
      if (isLive) {
        const envCount = state.lastState.envs ? state.lastState.envs.length : 0;
        if (envCount > 0) {
          updateDynamicMosaic(envCount);
        }
      }
    }
    calculateBandwidth();
    const nextDelay = parseInt(el.dynamicMosaicPoll?.value || '200', 10);
    dynamicMosaicTimerId = setTimeout(tick, nextDelay);
  }, delay);
}

function initDynamicMosaicControls() {
  if (el.dynamicMosaicPoll) {
    el.dynamicMosaicPoll.addEventListener('input', function() {
      const val = parseInt(this.value, 10);
      el.dynamicMosaicPollValue.textContent = val + 'ms';
      scheduleDynamicMosaic();
    });
  }
  if (!el.dynamicMosaicPollValue) return;
  el.dynamicMosaicPollValue.textContent = el.dynamicMosaicPoll.value + 'ms';
}

// Initialize all modules
initMap();
initMosaic();
initConfig();
initControlBindings();
initDynamicMosaic();
initInspector();
initTabs();
initDynamicMosaicControls();

// Start the update loop
update();
setInterval(update, 500);

// Start self-rescheduling dynamic mosaic poller
scheduleDynamicMosaic();

// Fetch inspector control state on startup and when switching to the inspector tab
fetchControlState();
setInterval(function() {
  if (isInspectorTabActive()) {
    updateInspectorScreen();
  }
}, 300);
