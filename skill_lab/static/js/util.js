function isTabActive(tabId) {
  const tab = document.getElementById(tabId);
  return tab && tab.classList.contains('active');
}

function isConfigTabActive() {
  return isTabActive('config-tab');
}

function isInspectorTabActive() {
  return isTabActive('inspector-tab');
}

function isMapTabActive() {
  return isTabActive('map-tab');
}

function isMosaicTabActive() {
  return isTabActive('mosaic-tab');
}

function isDynamicMosaicTabActive() {
  return isTabActive('dynamic-mosaic-tab');
}

function hpChip(value) {
  const label = (value * 100).toFixed(0) + '%';
  if (value >= 0.6) return '<span class="chip good">' + label + '</span>';
  if (value >= 0.25) return '<span class="chip warn">' + label + '</span>';
  return '<span class="chip bad">' + label + '</span>';
}

export { isTabActive, isConfigTabActive, isInspectorTabActive, isMapTabActive, isMosaicTabActive, isDynamicMosaicTabActive, hpChip };
