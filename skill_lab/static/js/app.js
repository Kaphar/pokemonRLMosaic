import { el, state } from './state.js';
import { isMosaicTabActive, isInspectorTabActive } from './util.js';
import { renderMap, renderStats, initMap, updateLavaToggle } from './map_tab.js';
import { updateMosaic, initMosaic } from './mosaic_tab.js';
import { updateDynamicMosaic, calculateBandwidth, initDynamicMosaic } from './dynamic_mosaic.js';
import {
  initInspector,
  updateInspectorSelect,
  fetchInspectorData,
  updateInspectorScreen,
  selectInspectorEnv,
} from './inspector_tab.js';
import { initConfig } from './config_tab.js';

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
      el.tabBtns.forEach(function(b) { b.classList.remove('active'); });
      el.tabPanes.forEach(function(p) { p.classList.remove('active'); });
      btn.classList.add('active');
      const target = btn.getAttribute('data-tab');
      document.getElementById(target).classList.add('active');
      if (target === 'mosaic-tab') {
        updateMosaic();
      }
      if (target === 'inspector-tab') {
        updateInspectorScreen();
        fetchInspectorData();
      }
    });
  });
}

// Initialize all modules
initMap();
initMosaic();
initConfig();
initDynamicMosaic();
initInspector();
initTabs();

// Start the update loop
update();
setInterval(update, 500);

setInterval(function() {
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
}, 200);

setInterval(function() {
  if (isInspectorTabActive()) {
    updateInspectorScreen();
  }
}, 300);
