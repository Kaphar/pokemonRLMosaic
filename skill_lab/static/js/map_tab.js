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

function renderMap(data) {
  state.lastState = data;
  el.envLayer.innerHTML = '';
  el.lavaLayer.innerHTML = '';

  const lavaZones = data.lava_zones || [];
  for (const zone of lavaZones) {
    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('x', zone[0]);
    rect.setAttribute('y', zone[1]);
    rect.setAttribute('width', 16);
    rect.setAttribute('height', 16);
    rect.setAttribute('fill', '#ff6b6b');
    rect.setAttribute('opacity', '0.5');
    el.lavaLayer.appendChild(rect);
  }

  for (const env of data.envs || []) {
    const circle = document.createElementNS(SVG_NS, 'circle');
    circle.setAttribute('cx', env.x);
    circle.setAttribute('cy', env.y);
    circle.setAttribute('r', 6);
    circle.setAttribute('fill', '#67f39b');
    circle.setAttribute('stroke', '#ffffff');
    circle.setAttribute('stroke-width', 1.2);
    const label = document.createElementNS(SVG_NS, 'text');
    label.setAttribute('x', env.x + 10);
    label.setAttribute('y', env.y - 8);
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
    el.lavaModeStatus.textContent = 'LAVA PLACEMENT MODE - click to place/remove zones';
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
      state.lavaHighlight.setAttribute('y', tileY);
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
        fetch('/api/lava', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ zones: zones })
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
        fetch('/api/lava', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ x: tileX, y: tileY })
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
  });

  el.zoomInBtn.addEventListener('click', function() { setZoom(1.15); });
  el.zoomOutBtn.addEventListener('click', function() { setZoom(0.85); });
  el.zoomResetBtn.addEventListener('click', function() { resetZoom(); });
  el.toggleLavaBtn.addEventListener('click', updateLavaToggle);

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
  el.mapSvg.addEventListener('mouseleave', hideCoordPopover);
  el.mapSvg.addEventListener('dblclick', handleMapDblClick);
  el.mapSvg.addEventListener('mousedown', function() {
    hideCoordPopover();
  });

  if (state.lavaPlacementMode) {
    el.lavaModeStatus.textContent = 'LAVA PLACEMENT MODE - click to place/remove zones';
    el.mapSvg.style.cursor = 'crosshair';
  }
}

export { renderMap, renderStats, initMap, updateLavaToggle, applyTransform, setZoom, resetZoom, clientToMapCoordinates, requestGameCoordinates, handleMapDblClick };
