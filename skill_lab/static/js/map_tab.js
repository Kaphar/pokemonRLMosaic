import { el, state, svg_w, svg_h, SVG_NS } from './state.js';
import { hpChip, isMapTabActive } from './util.js';

function applyTransform() {
  el.mapGroup.setAttribute('transform', 'translate(' + state.panX + ',' + state.panY + ') scale(' + state.zoomScale + ')');
}

function setZoom(delta) {
  const newScale = state.zoomScale * delta;
  if (newScale < 0.4 || newScale > 8) return;
  state.zoomScale = newScale;
  applyTransform();
}

function resetZoom() {
  state.zoomScale = 1;
  state.panX = 0;
  state.panY = 0;
  applyTransform();
}

function clientToMapCoordinates(clientX, clientY) {
  const svgRect = el.mapSvg.getBoundingClientRect();
  const relX = clientX - svgRect.left;
  const relY = clientY - svgRect.top;
  const fractionX = relX / svgRect.width;
  const fractionY = relY / svgRect.height;
  const svgX = fractionX * svg_w;
  const svgY = fractionY * svg_h;
  const invScale = 1 / state.zoomScale;
  const mapX = (svgX - state.panX) * invScale;
  const mapY = (svgY - state.panY) * invScale;
  return { mapX: mapX, mapY: mapY };
}

function requestGameCoordinates(mapX, mapY) {
  const url = '/api/map-coords?x=' + Math.round(mapX) + '&y=' + Math.round(mapY);
  return fetch(url, { cache: 'no-store' })
    .then(function(r) { return r.json(); })
    .catch(function() { return null; });
}

function logToTerminal(message) {
  const payload = JSON.stringify({ message: message });
  fetch('/api/log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
  }).catch(function() {});
}

function showCoordPopover(clientX, clientY, coords) {
  if (!state.coordPopover) return;
  const tileX = Math.round(coords.mapX / 16) * 16;
  const tileY = Math.round(coords.mapY / 16) * 16;
  requestGameCoordinates(coords.mapX, coords.mapY).then(function(data) {
    if (!data) {
      state.coordPopover.textContent =
        'Map XY: ' + tileX + ', ' + tileY + ' — (server unreachable)';
    } else {
      const mapIdHex = data.map_id.toString(16).toUpperCase().padStart(2, '0');
      state.coordPopover.textContent =
        'Map XY: ' + tileX + ', ' + tileY +
        ' | Game: map=0x' + mapIdHex + ' (' + data.map_name +
        '), x=' + data.x + ', y=' + data.y;
    }
    state.coordPopover.style.left = (clientX + 12) + 'px';
    state.coordPopover.style.top = (clientY + 12) + 'px';
    state.coordPopover.style.display = 'block';
  });
}

function handleMapDblClick(event) {
  if (!isMapTabActive()) return;
  const coords = clientToMapCoordinates(event.clientX, event.clientY);
  const tileX = Math.round(coords.mapX / 16) * 16;
  const tileY = Math.round(coords.mapY / 16) * 16;
  requestGameCoordinates(coords.mapX, coords.mapY).then(function(data) {
    const tileText = 'Map XY: ' + tileX + ', ' + tileY;
    if (!data) {
      logToTerminal(tileText + ' — (server unreachable)');
    } else {
      const mapIdHex = data.map_id.toString(16).toUpperCase().padStart(2, '0');
      logToTerminal(
        tileText +
        ' | Game: map=0x' + mapIdHex + ' (' + data.map_name +
        '), x=' + data.x + ', y=' + data.y
      );
    }
    showCoordPopover(event.clientX, event.clientY, coords);
  });
}

function startHoverCheck(event) {
  if (!isMapTabActive()) return;
  if (state.isPanning || state.lavaPlacementMode) return;
  if (state.hoverTimer !== null) clearTimeout(state.hoverTimer);
  const movementThreshold = 4;
  if (state.lastHoverPos) {
    const dx = event.clientX - state.lastHoverPos.x;
    const dy = event.clientY - state.lastHoverPos.y;
    if (Math.sqrt(dx * dx + dy * dy) > movementThreshold) {
      state.lastHoverPos = { x: event.clientX, y: event.clientY };
      return;
    }
  }
  state.lastHoverPos = { x: event.clientX, y: event.clientY };
  state.hoverTimer = setTimeout(function() {
    const coords = clientToMapCoordinates(event.clientX, event.clientY);
    showCoordPopover(event.clientX, event.clientY, coords);
    state.hoverTimer = null;
  }, 700);
}

function hideCoordPopover() {
  if (state.lastHoverPos) state.lastHoverPos = null;
  if (state.hoverTimer !== null) {
    clearTimeout(state.hoverTimer);
    state.hoverTimer = null;
  }
  if (state.coordPopover) {
    state.coordPopover.style.display = 'none';
  }
}

function renderZones(data) {
  const zones = data.zones || (data.lava_zones ? [{ type: 'lava', cells: data.lava_zones, label: 'Lava Zone', color: '#ff6b6b', opacity: 0.5 }] : []);
  if (!el.zoneList) return;
  el.zoneList.innerHTML = '';
  zones.forEach(function(zone) {
    const div = document.createElement('div');
    div.className = 'zone-item' + (zone.id === state.selectedZoneId ? ' selected' : '');
    div.dataset.zoneId = zone.id || '';

    const badgeColor = zone.type === 'action_mask' ? '#4a9eff' : '#ff6b6b';
    const badgeText = zone.type === 'action_mask' ? 'MASK' : 'LAVA';

    const labelSpan = document.createElement('span');
    labelSpan.className = 'zone-label';
    labelSpan.textContent = zone.label || zone.type;
    labelSpan.title = 'Double-click to rename';
    labelSpan.dataset.zoneId = zone.id || '';
    labelSpan.ondblclick = function(e) {
      e.stopPropagation();
      startRename(zone.id, zone.label || zone.type);
    };

    const cellCountSpan = document.createElement('span');
    cellCountSpan.className = 'zone-cell-count';
    cellCountSpan.textContent = String((zone.cells || []).length) + ' cells';

    const badge = document.createElement('span');
    badge.className = 'zone-type-badge';
    badge.style.border = '1px solid ' + badgeColor;
    badge.style.color = badgeColor;
    badge.textContent = badgeText;

    const leftDiv = document.createElement('div');
    leftDiv.style.display = 'flex';
    leftDiv.style.flex = '1';
    leftDiv.style.minWidth = '0';
    leftDiv.appendChild(labelSpan);
    leftDiv.appendChild(cellCountSpan);

    const rightDiv = document.createElement('div');
    rightDiv.style.display = 'flex';
    rightDiv.style.alignItems = 'center';
    rightDiv.style.gap = '4px';
    rightDiv.appendChild(badge);

    div.appendChild(leftDiv);
    div.appendChild(rightDiv);

    div.onclick = function() {
      selectZone(zone.id, zones);
    };
    el.zoneList.appendChild(div);
  });

  // Update detail panel
  updateZoneDetail(state.selectedZoneId, zones);
}

function startRename(zoneId, currentLabel) {
  state.isEditingZone = true;
  const zone = state.lastState.zones ? state.lastState.zones.find(z => z.id === zoneId) : null;
  if (!zone) return;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = currentLabel;
  input.style.background = 'rgba(15, 22, 34, 0.6)';
  input.style.border = '1px solid var(--accent)';
  input.style.borderRadius = '4px';
  input.style.padding = '2px 6px';
  input.style.color = 'var(--text)';
  input.style.fontSize = '0.8rem';
  input.style.width = '120px';
  const labelSpan = el.zoneList.querySelector('.zone-label[data-zone-id="' + zoneId + '"]');
  if (labelSpan) {
    labelSpan.parentNode.replaceChild(input, labelSpan);
    input.focus();
    input.select();
  }
  input.onkeydown = function(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitRename(zoneId, input.value);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelRename(zoneId, currentLabel);
    }
  };
  input.onblur = function() {
    commitRename(zoneId, input.value);
  };
}

function commitRename(zoneId, newName) {
  state.isEditingZone = false;
  if (!newName.trim()) return;
  const zones = state.lastState.zones || [];
  const zi = zones.findIndex(z => z.id === zoneId);
  if (zi >= 0) {
    zones[zi] = Object.assign({}, zones[zi], { label: newName.trim() });
    state.lastState = Object.assign({}, state.lastState, { zones: zones });
  }
  fetch('/api/zone-update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ zone_id: zoneId, label: newName.trim() })
  }).catch(function() {});
  renderZones(state.lastState);
}

function cancelRename(zoneId, oldName) {
  state.isEditingZone = false;
  const labelSpan = document.createElement('span');
  labelSpan.className = 'zone-label';
  labelSpan.textContent = oldName;
  labelSpan.title = 'Double-click to rename';
  labelSpan.dataset.zoneId = zoneId;
  labelSpan.ondblclick = function(e) {
    e.stopPropagation();
    startRename(zoneId, oldName);
  };
  const input = el.zoneList.querySelector('input[type="text"]');
  if (input && input.parentNode) {
    input.parentNode.replaceChild(labelSpan, input);
  }
}

function selectZone(zoneId, zones) {
  state.selectedZoneId = zoneId;
  const type = (zones.find(z => z.id === zoneId) || {}).type || 'lava';
  state.zonePlacingType = type;
  renderZones(state.lastState);
}

function _populateMilestoneOptions(selectEl, selected) {
  if (!selectEl) return;
  const checkpoints = state.availableCheckpoints || [];
  let options = '<option value="">None</option>';
  checkpoints.forEach(function(cp) {
    const name = cp.name || cp;
    const sel = name === selected ? ' selected' : '';
    options += '<option value="' + name + '"' + sel + '>' + name + '</option>';
  });
  selectEl.innerHTML = options;
}

function _populateActionOptions(selectEl, selectedList) {
  if (!selectEl) return;
  const actions = state.actionNames || [];
  let options = '';
  actions.forEach(function(a) {
    const sel = (selectedList || []).indexOf(a) >= 0 ? ' selected' : '';
    options += '<option value="' + a + '"' + sel + '>' + a + '</option>';
  });
  selectEl.innerHTML = options;
}

function updateZoneDetail(zoneId, zones) {
  if (!el.zoneDetail || !el.zoneDetailContent) return;
  const zone = zones.find(z => z.id === zoneId);
  if (!zone) {
    el.zoneDetail.classList.remove('expanded');
    return;
  }
  el.zoneDetail.classList.add('expanded');
  if (el.zoneDetailType) el.zoneDetailType.textContent = zone.type || '-';
  if (el.zoneDetailCells) el.zoneDetailCells.textContent = String((zone.cells || []).length);
  if (el.zoneDetailColor) {
    el.zoneDetailColor.value = (zone.color || (zone.type === 'action_mask' ? '#4a9eff' : '#ff6b6b')).replace('#', '');
  }
  if (el.zoneDetailOpacity) {
    var defaultOpacity = zone.type === 'action_mask' ? 0.25 : 0.5;
    el.zoneDetailOpacity.value = zone.opacity != null ? zone.opacity : defaultOpacity;
  }
  _populateActionOptions(el.zoneDetailAction, Array.isArray(zone.action) ? zone.action : (zone.action ? [zone.action] : []));
  _populateMilestoneOptions(el.zoneDetailActivateOn, zone.activate_on);
  _populateMilestoneOptions(el.zoneDetailDeactivateOn, zone.deactivate_on);
}

function saveZoneConfig(field, value) {
  if (!state.selectedZoneId) return;
  fetch('/api/zone-update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ zone_id: state.selectedZoneId, field: field, value: value })
  }).catch(function() {});
  // Optimistically update local state so the detail panel reflects the change
  // without waiting for the 500ms poll cycle.
  const zones = state.lastState.zones || [];
  const zi = zones.findIndex(z => z.id === state.selectedZoneId);
  if (zi >= 0) {
    zones[zi] = Object.assign({}, zones[zi], { [field]: value });
    state.lastState = Object.assign({}, state.lastState, { zones: zones });
    updateZoneDetail(state.selectedZoneId, zones);
  }
}

function renderMap(data) {
  state.lastState = data;
  el.envLayer.innerHTML = '';
  el.lavaLayer.innerHTML = '';

  // Render structured zones from data.zones (preferred) or legacy data.lava_zones
  var zones = data.zones || [];
  if (!zones.length && data.lava_zones) {
    zones = [{ type: 'lava', cells: data.lava_zones, label: 'Lava Zone', color: '#ff6b6b', opacity: 0.5 }];
  }
  for (const zone of zones) {
    const zoneType = zone.type || 'lava';
    if (!state.zoneVisibility[zoneType]) continue;
    const color = zone.color || (zoneType === 'action_mask' ? '#4a9eff' : '#ff6b6b');
    const opacity = zone.opacity != null ? zone.opacity : (zoneType === 'action_mask' ? 0.3 : 0.5);
    const cells = zone.cells || [];
    for (const cell of cells) {
      const rect = document.createElementNS(SVG_NS, 'rect');
      rect.setAttribute('x', cell[0]);
      rect.setAttribute('y', cell[1] - 8);
      rect.setAttribute('width', 16);
      rect.setAttribute('height', 16);
      rect.setAttribute('fill', color);
      rect.setAttribute('opacity', opacity);
      el.lavaLayer.appendChild(rect);
    }
  }

  for (const env of data.envs || []) {
    const halfTile = 8;
    const circle = document.createElementNS(SVG_NS, 'circle');
    circle.setAttribute('cx', env.x + halfTile);
    circle.setAttribute('cy', env.y + halfTile);
    circle.setAttribute('r', 6);
    circle.setAttribute('fill', '#67f39b');
    circle.setAttribute('stroke', '#ffffff');
    circle.setAttribute('stroke-width', 1.2);
    const label = document.createElementNS(SVG_NS, 'text');
    label.setAttribute('x', env.x + halfTile + 10);
    label.setAttribute('y', env.y + halfTile - 8);
    label.setAttribute('fill', '#eaf2ff');
    label.setAttribute('font-size', '12');
    label.textContent = 'E' + (env.env_index + 1);
    el.envLayer.appendChild(circle);
    el.envLayer.appendChild(label);
  }
}

function renderStats(data) {
  const envs = data.envs || [];
  el.statsBody.innerHTML = envs.map(function(env) {
    const hpHtml = hpChip(env.hp);
    const scoreText = (env.score >= 0 ? '+' : '') + env.score.toFixed(1);
    return '<tr><td>Env ' + (env.env_index + 1) + '</td><td>' + hpHtml + '</td><td>' + env.pkmn + '</td><td>' + env.trainer_wins + '</td><td>' + env.wild_wins + '</td><td>' + env.deaths + '</td><td>' + env.item_won_count + '</td><td>' + env.walls + '</td><td>' + env.steps + '</td><td>' + env.map_id.toString(16).toUpperCase().padStart(2, '0') + '</td><td>' + (env.raw_x ?? 0) + ',' + (env.raw_y ?? 0) + '</td><td>' + scoreText + '</td></tr>';
  }).join('');
  el.envCount.textContent = String(envs.length);
}

function initHighlightElements() {
  if (state.lavaHighlight) return;
  state.lavaHighlight = document.createElementNS(SVG_NS, 'rect');
  state.lavaHighlight.setAttribute('width', 16);
  state.lavaHighlight.setAttribute('height', 16);
  state.lavaHighlight.setAttribute('fill', '#ff6b6b');
  state.lavaHighlight.setAttribute('opacity', '0.3');
  state.lavaHighlight.setAttribute('stroke', '#ff6b6b');
  state.lavaHighlight.setAttribute('stroke-width', '1');
  state.lavaHighlight.setAttribute('pointer-events', 'none');
  el.highlightLayer.appendChild(state.lavaHighlight);
  state.lavaHighlight.style.display = 'none';

  state.selectRect = document.createElementNS(SVG_NS, 'rect');
  state.selectRect.setAttribute('fill', '#ff6b6b');
  state.selectRect.setAttribute('opacity', '0.15');
  state.selectRect.setAttribute('stroke', '#ff6b6b');
  state.selectRect.setAttribute('stroke-width', '1');
  state.selectRect.setAttribute('stroke-dasharray', '4,2');
  state.selectRect.setAttribute('pointer-events', 'none');
  el.highlightLayer.appendChild(state.selectRect);
  state.selectRect.style.display = 'none';
}

function updateLavaToggle() {
  state.lavaPlacementMode = !state.lavaPlacementMode;
  el.toggleLavaBtn.classList.toggle('toggle-active', state.lavaPlacementMode);
  if (state.lavaPlacementMode) {
    var zone = state.lastState.zones ? state.lastState.zones.find(function(z) { return z.id === state.selectedZoneId; }) : null;
    var type = (zone && zone.type) || state.zonePlacingType || 'lava';
    var modeText = type === 'action_mask' ? 'ACTION MASK' : 'ZONE';
    el.lavaModeStatus.textContent = modeText + ' PLACEMENT MODE - click to place/remove zones';
    el.mapSvg.style.cursor = 'crosshair';
  } else {
    el.lavaModeStatus.textContent = '';
    el.mapSvg.style.cursor = '';
    if (state.lavaHighlight) state.lavaHighlight.style.display = 'none';
  }
}

function initMap() {
  initHighlightElements();

  el.mapSvg.addEventListener('wheel', function(event) {
    event.preventDefault();
    event.stopPropagation();
    const delta = event.deltaY < 0 ? 1.15 : 0.85;
    setZoom(delta);
  }, { passive: false });

  el.mapSvg.addEventListener('mousedown', function(event) {
    if (event.button !== 0) return;
    if (state.lavaPlacementMode) {
      state.dragStart = { x: event.clientX, y: event.clientY };
      state.clickStart = null;
      state.isPanning = false;
      return;
    }
    state.clickStart = { x: event.clientX, y: event.clientY };
    state.isPanning = true;
    state.panStart = { x: event.clientX, y: event.clientY };
    el.mapSvg.classList.add('grabbing');
  });

  document.addEventListener('mousemove', function(event) {
    if (state.lavaPlacementMode && state.dragStart) {
      const rect = el.mapSvg.getBoundingClientRect();
      const svgX = ((event.clientX - rect.left) / rect.width) * svg_w;
      const svgY = ((event.clientY - rect.top) / rect.height) * svg_h;
      const invScale = 1 / state.zoomScale;
      const viewBoxX = (svgX - state.panX) * invScale;
      const viewBoxY = (svgY - state.panY) * invScale;
      const startRect = el.mapSvg.getBoundingClientRect();
      const startSvgX = ((state.dragStart.x - startRect.left) / startRect.width) * svg_w;
      const startSvgY = ((state.dragStart.y - startRect.top) / startRect.height) * svg_h;
      const startViewX = (startSvgX - state.panX) * invScale;
      const startViewY = (startSvgY - state.panY) * invScale;
      const startX = Math.min(startViewX, viewBoxX);
      const startY = Math.min(startViewY, viewBoxY);
      const endX = Math.max(startViewX, viewBoxX);
      const endY = Math.max(startViewY, viewBoxY);
      state.selectRect.setAttribute('x', startX);
      state.selectRect.setAttribute('y', startY);
      state.selectRect.setAttribute('width', endX - startX);
      state.selectRect.setAttribute('height', endY - startY);
      state.selectRect.style.display = 'block';
      state.lavaHighlight.style.display = 'none';
      return;
    }
    if (!state.isPanning && !state.lavaPlacementMode) return;
    if (state.isPanning) {
      const dx = event.clientX - state.panStart.x;
      const dy = event.clientY - state.panStart.y;
      state.panX += dx;
      state.panY += dy;
      state.panStart = { x: event.clientX, y: event.clientY };
      applyTransform();
    }
    if (state.lavaPlacementMode) {
      const rect = el.mapSvg.getBoundingClientRect();
      const svgX = ((event.clientX - rect.left) / rect.width) * svg_w;
      const svgY = ((event.clientY - rect.top) / rect.height) * svg_h;
      const invScale = 1 / state.zoomScale;
      const viewBoxX = (svgX - state.panX) * invScale;
      const viewBoxY = (svgY - state.panY) * invScale;
      const tileX = Math.round(viewBoxX / 16) * 16;
      const tileY = Math.round(viewBoxY / 16) * 16;
      state.lavaHighlight.setAttribute('x', tileX);
      state.lavaHighlight.setAttribute('y', tileY - 8);
      state.lavaHighlight.style.display = 'block';
    }
  });

  document.addEventListener('mouseup', function(event) {
    if (state.lavaPlacementMode && state.dragStart) {
      if (state.selectRect.style.display !== 'none') {
        const rect = el.mapSvg.getBoundingClientRect();
        const invScale = 1 / state.zoomScale;
        const startSvgX = ((state.dragStart.x - rect.left) / rect.width) * svg_w;
        const startSvgY = ((state.dragStart.y - rect.top) / rect.height) * svg_h;
        const startViewX = (startSvgX - state.panX) * invScale;
        const startViewY = (startSvgY - state.panY) * invScale;
        const endSvgX = ((event.clientX - rect.left) / rect.width) * svg_w;
        const endSvgY = ((event.clientY - rect.top) / rect.height) * svg_h;
        const endViewX = (endSvgX - state.panX) * invScale;
        const endViewY = (endSvgY - state.panY) * invScale;
        const startX = Math.min(startViewX, endViewX);
        const startY = Math.min(startViewY, endViewY);
        const endX = Math.max(startViewX, endViewX);
        const endY = Math.max(startViewY, endViewY);
        const zones = [];
        for (let tx = Math.floor(startX / 16); tx <= Math.floor(endX / 16); tx++) {
          for (let ty = Math.floor(startY / 16); ty <= Math.floor(endY / 16); ty++) {
            zones.push({ x: tx * 16, y: ty * 16 });
          }
        }
        fetch('/api/zones', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ zones: zones, zone_type: state.zonePlacingType, zone_id: state.selectedZoneId })
        }).then(function(r) { return r.json(); }).then(function(data) {
        }).catch(function() {});
      } else {
        const rect = el.mapSvg.getBoundingClientRect();
        const svgX = ((event.clientX - rect.left) / rect.width) * svg_w;
        const svgY = ((event.clientY - rect.top) / rect.height) * svg_h;
        const invScale = 1 / state.zoomScale;
        const viewBoxX = (svgX - state.panX) * invScale;
        const viewBoxY = (svgY - state.panY) * invScale;
        const tileX = Math.round(viewBoxX / 16) * 16;
        const tileY = Math.round(viewBoxY / 16) * 16;
        fetch('/api/zones', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ x: tileX, y: tileY, zone_type: state.zonePlacingType, zone_id: state.selectedZoneId })
        }).then(function(r) { return r.json(); }).then(function() {
        }).catch(function() {});
      }
      state.dragStart = null;
      state.selectRect.style.display = 'none';
      return;
    }
    if (!state.isPanning) return;
    state.isPanning = false;
    state.clickStart = null;
    el.mapSvg.classList.remove('grabbing');
  });

  document.addEventListener('keydown', function(event) {
    if (event.key === 'l' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      updateLavaToggle();
    }
    if (isMapTabActive() && (event.key === '+' || event.key === '-' || event.key === '=')) {
      event.preventDefault();
      if (event.key === '+' || event.key === '=') {
        setZoom(1.15);
      } else {
        setZoom(0.85);
      }
    }
    if (isMapTabActive() && event.key === 'r' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      resetZoom();
    }
    console.log(event)
    if (event.key === 'c') {
      event.preventDefault();
      if (state.lastMousePos) {
        const coords = clientToMapCoordinates(state.lastMousePos.x, state.lastMousePos.y);
        const tileX = Math.round(coords.mapX / 16) * 16;
        const tileY = Math.round(coords.mapY / 16) * 16;
        let logMsg = 'Map XY: ' + Math.round(coords.mapX) + ', ' + Math.round(coords.mapY) +
          ' | Tile: ' + tileX + ', ' + tileY;
        if (state.lavaHighlight && state.lavaHighlight.style.display !== 'none') {
          const hlX = parseInt(state.lavaHighlight.getAttribute('x'), 10);
          const hlY = parseInt(state.lavaHighlight.getAttribute('y'), 10);
          logMsg += ' | Highlight: ' + hlX + ', ' + hlY + ' (rendered rect)';
        }
        if (state.lavaPlacementMode) {
          logMsg += ' | Placement mode: ' + (state.zonePlacingType || 'lava');
        }
        requestGameCoordinates(coords.mapX, coords.mapY).then(function(data) {
          if (data) {
            const mapIdHex = data.map_id.toString(16).toUpperCase().padStart(2, '0');
            const fullMsg = logMsg +
              ' | Game: map=0x' + mapIdHex + ' (' + data.map_name +
              '), x=' + data.x + ', y=' + data.y;
            console.log(fullMsg);
            navigator.clipboard.writeText(fullMsg).catch(function() {});
          } else {
            const fullMsg = logMsg + ' | Game: (server unreachable)';
            console.log(fullMsg);
            navigator.clipboard.writeText(fullMsg).catch(function() {});
          }
        });
      } else {
        console.log('No mouse position available on map');
      }
    }
  });

  el.zoomInBtn.addEventListener('click', function() { setZoom(1.15); });
  el.zoomOutBtn.addEventListener('click', function() { setZoom(0.85); });
  el.zoomResetBtn.addEventListener('click', function() { resetZoom(); });
  el.toggleLavaBtn.addEventListener('click', updateLavaToggle);
  if (el.zoneVisibilityToggle) {
    el.zoneVisibilityToggle.addEventListener('click', function() {
      const anyVisible = state.zoneVisibility.lava || state.zoneVisibility.action_mask;
      const newVisible = !anyVisible;
      state.zoneVisibility.lava = newVisible;
      state.zoneVisibility.action_mask = newVisible;
      this.classList.toggle('toggle-active', anyVisible === false);
    });
  }
  if (el.addZoneBtn) {
    el.addZoneBtn.addEventListener('click', function() {
      const type = state.zonePlacingType || 'lava';
      fetch('/api/zone-create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zone_type: type })
      }).then(function(r) { return r.json(); })
        .then(function(data) {
          if (data && data.zone_id) {
            state.selectedZoneId = data.zone_id;
            renderZones(state.lastState);
          }
        })
        .catch(function() {});
    });
  }
  if (el.deleteZoneBtn) {
    el.deleteZoneBtn.addEventListener('click', function() {
      if (!state.selectedZoneId) return;
      fetch('/api/zone-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zone_id: state.selectedZoneId })
      }).then(function(r) { return r.json(); })
        .then(function() {
          state.selectedZoneId = null;
          renderZones(state.lastState);
        })
        .catch(function() {});
    });
  }
  if (el.zoneDetailColor) {
    el.zoneDetailColor.addEventListener('input', function() {
      saveZoneConfig('color', '#' + this.value);
    });
  }
  if (el.zoneDetailOpacity) {
    el.zoneDetailOpacity.addEventListener('input', function() {
      saveZoneConfig('opacity', parseFloat(this.value));
    });
  }
  if (el.zoneDetailAction) {
    el.zoneDetailAction.addEventListener('change', function() {
      const selected = Array.from(this.selectedOptions).map(function(o) { return o.value; });
      const zone = state.lastState.zones ? state.lastState.zones.find(z => z.id === state.selectedZoneId) : null;
      if (!zone) return;
      saveZoneConfig('action', selected.length === 1 ? selected[0] : selected);
    });
  }
  if (el.zoneDetailActivateOn) {
    el.zoneDetailActivateOn.addEventListener('change', function() {
      saveZoneConfig('activate_on', this.value || null);
    });
  }
  if (el.zoneDetailDeactivateOn) {
    el.zoneDetailDeactivateOn.addEventListener('change', function() {
      saveZoneConfig('deactivate_on', this.value || null);
    });
  }

  const popover = document.createElement('div');
  popover.className = 'coord-popover';
  popover.style.position = 'fixed';
  popover.style.pointerEvents = 'none';
  popover.style.display = 'none';
  popover.style.padding = '4px 8px';
  popover.style.background = 'rgba(15, 20, 26, 0.9)';
  popover.style.border = '1px solid #4a5a75';
  popover.style.borderRadius = '4px';
  popover.style.color = '#eaf2ff';
  popover.style.fontSize = '12px';
  popover.style.fontFamily = 'monospace';
  popover.style.zIndex = '1000';
  popover.style.whiteSpace = 'nowrap';
  document.body.appendChild(popover);
  state.coordPopover = popover;

  el.mapSvg.addEventListener('mousemove', startHoverCheck);
  el.mapSvg.addEventListener('mousemove', function(event) {
    state.lastMousePos = { x: event.clientX, y: event.clientY };
  });
  el.mapSvg.addEventListener('mouseleave', hideCoordPopover);
  el.mapSvg.addEventListener('dblclick', handleMapDblClick);
  el.mapSvg.addEventListener('mousedown', function() {
    hideCoordPopover();
  });

  if (state.lavaPlacementMode) {
    var _zone = state.lastState.zones ? state.lastState.zones.find(function(z) { return z.id === state.selectedZoneId; }) : null;
    var _type = (_zone && _zone.type) || state.zonePlacingType || 'lava';
    var _modeText = _type === 'action_mask' ? 'ACTION MASK' : 'ZONE';
    el.lavaModeStatus.textContent = _modeText + ' PLACEMENT MODE - click to place/remove zones';
    el.mapSvg.style.cursor = 'crosshair';
  } else {
    // Smooth default zoom toward the focus point (1040, 3376)
    setTimeout(function() {
       state.zoomScale = 3.0;
       var focusX = 1040, focusY = 3376;
       state.panX = svg_w / 2 - state.zoomScale * focusX;
       state.panY = svg_h / 2 - state.zoomScale * focusY;
       applyTransform();
    }, 100);
  }
}

export { renderMap, renderStats, initMap, updateLavaToggle, applyTransform, setZoom, resetZoom, clientToMapCoordinates, requestGameCoordinates, handleMapDblClick, renderZones };
