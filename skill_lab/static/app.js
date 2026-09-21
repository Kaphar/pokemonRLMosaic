const svg_w = window.DASHBOARD_SVG_W;
const svg_h = window.DASHBOARD_SVG_H;

const mapSvg = document.getElementById('map');
const envLayer = document.getElementById('env-layer');
const lavaLayer = document.getElementById('lava-layer');
const statsBody = document.getElementById('stats-body');
const envCount = document.getElementById('env-count');
const status = document.getElementById('status');
const mosaicImage = document.getElementById('mosaic-image');
const mosaicStatus = document.getElementById('mosaic-status');
const dynamicMosaicGrid = document.getElementById('dynamic-mosaic-grid');
const dynamicMosaicStatus = document.getElementById('dynamic-mosaic-status');
const dynamicMosaicPageSize = document.getElementById('dynamic-mosaic-page-size');
const dynamicMosaicPageSizeValue = document.getElementById('dynamic-mosaic-page-size-value');
const dynamicMosaicPrevBtn = document.getElementById('dynamic-mosaic-prev-btn');
const dynamicMosaicNextBtn = document.getElementById('dynamic-mosaic-next-btn');
const dynamicMosaicPageIndicator = document.getElementById('dynamic-mosaic-page-indicator');
const inspectorEnvSelect = document.getElementById('inspector-env-select');
const inspectorScreen = document.getElementById('inspector-screen');
const inspectorDetails = document.getElementById('inspector-details');
const inspectorMemoryBody = document.getElementById('inspector-body');
const inspectorStatus = document.getElementById('inspector-status');
const tabBtns = document.querySelectorAll('.tab-bar .tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

let mosaicObjectUrl = null;
let dynamicMosaicObjectUrls = {};
let inspectorObjectUrl = null;
let lastInspectorData = null;
let selectedInspectorEnv = 0;
let dynamicMosaicCurrentPage = 0;
let dynamicMosaicPageSizeVal = 42;
let zoomScale = 1;
let panX = 0;
let panY = 0;
let isPanning = false;
let lavaPlacementMode = true;
let clickStart = null;
let dragStart = null;
let panStart = { x: 0, y: 0 };
let lastState = { envs: [], lava_zones: [] };
let bandwidthHistory = [];
let lastBytesSent = 0;
let lastBandwidthTime = Date.now();

const mapGroup = document.getElementById('map-zoom-group');
const highlightLayer = document.getElementById('highlight-layer');

const lavaHighlight = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
lavaHighlight.setAttribute('width', 16);
lavaHighlight.setAttribute('height', 16);
lavaHighlight.setAttribute('fill', '#ff6b6b');
lavaHighlight.setAttribute('opacity', '0.3');
lavaHighlight.setAttribute('stroke', '#ff6b6b');
lavaHighlight.setAttribute('stroke-width', '1');
lavaHighlight.setAttribute('pointer-events', 'none');
highlightLayer.appendChild(lavaHighlight);
lavaHighlight.style.display = 'none';

const selectRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
selectRect.setAttribute('fill', '#ff6b6b');
selectRect.setAttribute('opacity', '0.15');
selectRect.setAttribute('stroke', '#ff6b6b');
selectRect.setAttribute('stroke-width', '1');
selectRect.setAttribute('stroke-dasharray', '4,2');
selectRect.setAttribute('pointer-events', 'none');
highlightLayer.appendChild(selectRect);
selectRect.style.display = 'none';

function applyTransform() {
    mapGroup.setAttribute('transform', 'translate(' + panX + ',' + panY + ') scale(' + zoomScale + ')');
}

function setZoom(delta) {
    const newScale = zoomScale * delta;
    if (newScale < 0.4 || newScale > 8) return;
    zoomScale = newScale;
    applyTransform();
}

function resetZoom() {
    zoomScale = 1;
    panX = 0;
    panY = 0;
    applyTransform();
}

function hpChip(value) {
    const label = (value * 100).toFixed(0) + '%';
    if (value >= 0.6) return '<span class="chip good">' + label + '</span>';
    if (value >= 0.25) return '<span class="chip warn">' + label + '</span>';
    return '<span class="chip bad">' + label + '</span>';
}

mosaicImage.addEventListener('error', function() {
    mosaicStatus.textContent = 'offline';
});

const zoomInBtn = document.getElementById('zoom-in');
const zoomOutBtn = document.getElementById('zoom-out');
const zoomResetBtn = document.getElementById('zoom-reset');
const toggleLavaBtn = document.getElementById('toggle-lava');
const lavaModeStatus = document.getElementById('lava-mode-status');
const maxStepsSlider = document.getElementById('max-steps');
const maxStepsValue = document.getElementById('max-steps-value');
const saveOnCatchCheckbox = document.getElementById('save-on-catch');
const applyConfigBtn = document.getElementById('apply-config-btn');
const configStatus = document.getElementById('config-status');

if (maxStepsSlider) {
    maxStepsSlider.addEventListener('input', function() {
        maxStepsValue.textContent = String(maxStepsSlider.value);
    });
}

if (applyConfigBtn) {
    applyConfigBtn.addEventListener('click', function() {
        var payload = {
            max_steps: parseInt(maxStepsSlider.value, 10),
            save_on_catch: saveOnCatchCheckbox.checked,
        };
        configStatus.textContent = 'saving...';
        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                configStatus.textContent = data.status || 'saved';
            })
            .catch(function() {
                configStatus.textContent = 'error';
            });
    });
}

function renderMap(data) {
    lastState = data;
    envLayer.innerHTML = '';
    lavaLayer.innerHTML = '';
    const lavaZones = data.lava_zones || [];
    for (const zone of lavaZones) {
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', zone[0]);
        rect.setAttribute('y', zone[1]);
        rect.setAttribute('width', 16);
        rect.setAttribute('height', 16);
        rect.setAttribute('fill', '#ff6b6b');
        rect.setAttribute('opacity', '0.5');
        lavaLayer.appendChild(rect);
    }

    for (const env of data.envs || []) {
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', env.x);
        circle.setAttribute('cy', env.y);
        circle.setAttribute('r', 6);
        circle.setAttribute('fill', '#67f39b');
        circle.setAttribute('stroke', '#ffffff');
        circle.setAttribute('stroke-width', 1.2);
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', env.x + 10);
        label.setAttribute('y', env.y - 8);
        label.setAttribute('fill', '#eaf2ff');
        label.setAttribute('font-size', '12');
        label.textContent = 'E' + (env.env_index + 1);
        envLayer.appendChild(circle);
        envLayer.appendChild(label);
    }
}

function renderStats(data) {
    const envs = data.envs || [];
    statsBody.innerHTML = envs.map(function(env) {
        var hpHtml = hpChip(env.hp);
        var scoreText = (env.score >= 0 ? '+' : '') + env.score.toFixed(1);
        return '<tr><td>Env ' + (env.env_index + 1) + '</td><td>' + hpHtml + '</td><td>' + env.pkmn + '</td><td>' + env.trainer_wins + '</td><td>' + env.wild_wins + '</td><td>' + env.deaths + '</td><td>' + env.item_won_count + '</td><td>' + env.walls + '</td><td>' + env.steps + '</td><td>' + env.map_id.toString(16).toUpperCase().padStart(2, '0') + '</td><td>' + (env.raw_x ?? 0) + ',' + (env.raw_y ?? 0) + '</td><td>' + scoreText + '</td></tr>';
    }).join('');
    envCount.textContent = String(envs.length);
}

function updateInspectorSelect(envs) {
    const currentVal = inspectorEnvSelect.value;
    inspectorEnvSelect.innerHTML = envs.map(function(env) {
        return '<option value="' + env.env_index + '">Env ' + (env.env_index + 1) + ' - HP: ' + (env.hp * 100).toFixed(0) + '%</option>';
    }).join('');
    if (currentVal !== '' && envs.some(e => e.env_index == currentVal)) {
        inspectorEnvSelect.value = currentVal;
    }
    selectedInspectorEnv = parseInt(inspectorEnvSelect.value) || 0;
}

function renderInspectorDetails(data) {
    if (!inspectorDetails) return;

    if (!data || data.error) {
        inspectorDetails.innerHTML = '<div style="color: #ff6b6b; padding: 12px;">' +
            (data && data.error ? 'Error: ' + data.error : 'No data available') +
            '</div>';
        return;
    }

    lastInspectorData = data;
    let html = '';

    // ---- Environment Directives ----
    const directives = data.directives || {};
    html += '<div class="inspector-section">';
    html += '<h3>Environment Directives</h3>';
    html += '<table class="inspector-table">';
    html += '<tr><td class="inspect-label">Env Name</td><td>' + (directives.env_name || '-') + '</td></tr>';
    html += '<tr><td class="inspect-label">ROM</td><td>[' + (directives.rom_label || 'Unknown') + ']</td></tr>';
    html += '<tr><td class="inspect-label">Target Starter</td><td>' + (directives.target_starter || 'Any') + '</td></tr>';
    html += '<tr><td class="inspect-label">Save on Catch</td><td>' + (directives.save_on_catch ? 'Yes' : 'No') + '</td></tr>';
    html += '<tr><td class="inspect-label">Reset on Catch</td><td>' + (directives.reset_on_catch ? 'Yes' : 'No') + '</td></tr>';
    if (Array.isArray(directives.catch_directive) && directives.catch_directive.length) {
        let catchStr = directives.catch_directive.slice(0, 4).join(', ');
        if (directives.catch_directive.length > 4) catchStr += ' (+' + (directives.catch_directive.length - 4) + ' more)';
        html += '<tr><td class="inspect-label">Catch Directives</td><td>' + catchStr + '</td></tr>';
    }
    if (Array.isArray(directives.train_directive) && directives.train_directive.length) {
        let trainStr = directives.train_directive.slice(0, 3).join(', ');
        if (directives.train_directive.length > 3) trainStr += ' (+' + (directives.train_directive.length - 3) + ' more)';
        html += '<tr><td class="inspect-label">Train Directives</td><td>' + trainStr + '</td></tr>';
    }
    html += '</table>';
    html += '</div>';

    // ---- Game Stats ----
    const stats = data.stats || {};
    html += '<div class="inspector-section">';
    html += '<h3>Game Stats</h3>';
    html += '<table class="inspector-table">';
    html += '<tr><td class="inspect-label">HP</td><td>' + (stats.hp !== undefined && stats.hp !== null ? (stats.hp * 100).toFixed(0) + '%' : '-') + '</td></tr>';
    html += '<tr><td class="inspect-label">Level Sum</td><td>' + (stats.level_sum || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Badges</td><td>' + (stats.badges || 0) + '/8</td></tr>';
    html += '<tr><td class="inspect-label">Events</td><td>' + (stats.events || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Steps</td><td>' + (stats.steps || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Trainer Wins</td><td>' + (stats.trainer_wins || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Wild Wins</td><td>' + (stats.wild_wins || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Wall Collisions</td><td>' + (stats.walls || 0) + '</td></tr>';
    html += '</table>';
    html += '</div>';

    // ---- World Info ----
    const mapId = stats.map_id || 0;
    html += '<div class="inspector-section">';
    html += '<h3>World Info</h3>';
    html += '<table class="inspector-table">';
    html += '<tr><td class="inspect-label">Map ID</td><td>0x' + mapId.toString(16).toUpperCase().padStart(2, '0') + '</td></tr>';
    html += '<tr><td class="inspect-label">X Position</td><td>' + (stats.x ?? 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Y Position</td><td>' + (stats.y ?? 0) + '</td></tr>';
    html += '</table>';
    html += '</div>';

    // ---- Party ----
    const party = Array.isArray(data.party) ? data.party : [];
    html += '<div class="inspector-section">';
    html += '<h3>Pok&eacute;mons Party (' + party.length + '/6)</h3>';
    if (party.length === 0) {
        html += '<div style="color: #8aa0c7; font-size: 0.85rem;">No Pok&eacute;mon in party</div>';
    } else {
        html += '<table class="inspector-table party-table">';
        html += '<thead><tr><th>#</th><th>Nickname</th><th>Species</th><th>Lv</th><th>HP</th><th>Types</th><th>DVs (Atk/Def/Spe/SpA)</th><th>Shiny</th></tr></thead>';
        html += '<tbody>';
        for (let i = 0; i < party.length; i++) {
            const p = party[i];
            const nickname = p.nickname || p.speciesName || '?';
            const species = p.speciesName || '?';
            const level = p.level || 0;
            const hp = (p.curHP !== undefined ? p.curHP : '?');
            const maxHp = (p.maxHP !== undefined ? p.maxHP : '?');
            const type1 = p.type1Name || '?';
            const type2 = (p.type2Name && p.type2Name !== type1) ? '/' + p.type2Name : '';
            const dvStr = (p.ivAttack !== undefined)
                ? p.ivAttack + '/' + p.ivDefense + '/' + p.ivSpeed + '/' + p.ivSpAttack
                : '-';
            const shinyStr = p.isShiny ? 'Yes' : 'No';
            html += '<tr>';
            html += '<td>' + (i + 1) + '</td>';
            html += '<td>' + nickname + '</td>';
            html += '<td>' + species + '</td>';
            html += '<td>' + level + '</td>';
            html += '<td>' + hp + '/' + maxHp + '</td>';
            html += '<td>' + type1 + type2 + '</td>';
            html += '<td>' + dvStr + '</td>';
            html += '<td>' + shinyStr + '</td>';
            html += '</tr>';
        }
        html += '</tbody>';
        html += '</table>';
    }
    html += '</div>';

    // ---- Trainer Info ----
    const trainer = data.trainer || {};
    if (trainer.name || trainer.money !== undefined || trainer.coins !== undefined) {
        html += '<div class="inspector-section">';
        html += '<h3>Trainer Info</h3>';
        html += '<table class="inspector-table">';
        html += '<tr><td class="inspect-label">Name</td><td>' + (trainer.name || '-') + '</td></tr>';
        html += '<tr><td class="inspect-label">Money</td><td>$' + (trainer.money || 0) + '</td></tr>';
        html += '<tr><td class="inspect-label">Coins</td><td>' + (trainer.coins || 0) + '</td></tr>';
        html += '<tr><td class="inspect-label">Badges</td><td>' + (trainer.badge_count || 0) + '/8</td></tr>';
        html += '</table>';
        html += '</div>';
    }

    // ---- Bag ----
    const bag = Array.isArray(data.bag) ? data.bag : [];
    html += '<div class="inspector-section">';
    html += '<h3>Bag (' + bag.length + ' items)</h3>';
    if (bag.length === 0) {
        html += '<div style="color: #8aa0c7; font-size: 0.85rem;">Bag is empty</div>';
    } else {
        html += '<table class="inspector-table">';
        for (const item of bag) {
            html += '<tr><td>' + (item.name || 'Item #' + item.id) + '</td><td style="text-align:right;">' + (item.quantity || 1) + 'x</td></tr>';
        }
        html += '</table>';
    }
    html += '</div>';

    // ---- Recent Actions ----
    const recentActions = Array.isArray(data.recent_actions) ? data.recent_actions : [];
    if (recentActions.length) {
        html += '<div class="inspector-section">';
        html += '<h3>Recent Actions</h3>';
        html += '<div style="font-family: monospace; color: #8aa0c7; font-size: 0.8rem;">' + recentActions.join(' \u2192 ') + '</div>';
        html += '</div>';
    }

    inspectorDetails.innerHTML = html;
}

function renderInspectorMemoryWatch(data) {
    if (!inspectorMemoryBody) return;
    inspectorMemoryBody.innerHTML = '';
    if (!data || !data.memory_watch || !Array.isArray(data.memory_watch)) {
        if (inspectorStatus) inspectorStatus.textContent = 'offline';
        return;
    }
    data.memory_watch.forEach(function(entry) {
        var cls = entry.changed ? ' changed' : '';
        var row = '<tr class="' + cls + '">' +
            '<td>0x' + entry.address.toString(16).toUpperCase().padStart(4, '0') + '</td>' +
            '<td>' + (entry.value !== undefined && entry.value !== null ? entry.value : '-') + '</td>' +
            '<td>' + (entry.description || '') + '</td>' +
            '</tr>';
        inspectorMemoryBody.insertAdjacentHTML('beforeend', row);
    });
    if (inspectorStatus) inspectorStatus.textContent = 'live';
}

function renderInspector(data) {
    renderInspectorDetails(data);
    renderInspectorMemoryWatch(data);
}

function fetchInspectorData() {
    const idx = selectedInspectorEnv;
    fetch('/api/inspector?env=' + idx, { cache: 'no-store' })
        .then(function(r) {
            if (r.status === 204) return null;
            return r.json();
        })
        .then(function(data) {
            if (data) {
                renderInspector(data);
            }
        })
        .catch(function() {
            if (inspectorStatus) inspectorStatus.textContent = 'offline';
        });
}

function isConfigTabActive() {
    const tab = document.getElementById('config-tab');
    return tab && tab.classList.contains('active');
}

function isInspectorTabActive() {
    const tab = document.getElementById('inspector-tab');
    return tab && tab.classList.contains('active');
}

function isMapTabActive() {
    const tab = document.getElementById('map-tab');
    return tab && tab.classList.contains('active');
}

function update() {
    fetch('/api/state', { cache: 'no-store' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data || !Array.isArray(data.envs)) return;
            status.textContent = 'live';
            renderMap(data);
            renderStats(data);
            updateInspectorSelect(data.envs);
        })
        .catch(function() {
            status.textContent = 'offline';
        });
    if (document.getElementById('mosaic-tab').classList.contains('active')) {
        updateMosaic();
    }
    if (isInspectorTabActive()) {
        fetchInspectorData();
    }
}

mapSvg.addEventListener('wheel', function(event) {
    event.preventDefault();
    event.stopPropagation();
    const delta = event.deltaY < 0 ? 1.15 : 0.85;
    setZoom(delta);
}, { passive: false });

mapSvg.addEventListener('mousedown', function(event) {
    if (event.button !== 0) return;
    if (lavaPlacementMode) {
        dragStart = { x: event.clientX, y: event.clientY };
        clickStart = null;
        isPanning = false;
        return;
    }
    clickStart = { x: event.clientX, y: event.clientY };
    isPanning = true;
    panStart = { x: event.clientX, y: event.clientY };
    mapSvg.classList.add('grabbing');
});

document.addEventListener('mousemove', function(event) {
    if (lavaPlacementMode && dragStart) {
        const rect = mapSvg.getBoundingClientRect();
        const svgX = ((event.clientX - rect.left) / rect.width) * svg_w;
        const svgY = ((event.clientY - rect.top) / rect.height) * svg_h;
        const invScale = 1 / zoomScale;
        const viewBoxX = (svgX - panX) * invScale;
        const viewBoxY = (svgY - panY) * invScale;
        const startRect = mapSvg.getBoundingClientRect();
        const startSvgX = ((dragStart.x - startRect.left) / startRect.width) * svg_w;
        const startSvgY = ((dragStart.y - startRect.top) / startRect.height) * svg_h;
        const startViewX = (startSvgX - panX) * invScale;
        const startViewY = (startSvgY - panY) * invScale;
        const startX = Math.min(startViewX, viewBoxX);
        const startY = Math.min(startViewY, viewBoxY);
        const endX = Math.max(startViewX, viewBoxX);
        const endY = Math.max(startViewY, viewBoxY);
        selectRect.setAttribute('x', startX);
        selectRect.setAttribute('y', startY);
        selectRect.setAttribute('width', endX - startX);
        selectRect.setAttribute('height', endY - startY);
        selectRect.style.display = 'block';
        lavaHighlight.style.display = 'none';
        return;
    }
    if (!isPanning && !lavaPlacementMode) return;
    if (isPanning) {
        const dx = event.clientX - panStart.x;
        const dy = event.clientY - panStart.y;
        panX += dx;
        panY += dy;
        panStart = { x: event.clientX, y: event.clientY };
        applyTransform();
    }
    if (lavaPlacementMode) {
        const rect = mapSvg.getBoundingClientRect();
        const svgX = ((event.clientX - rect.left) / rect.width) * svg_w;
        const svgY = ((event.clientY - rect.top) / rect.height) * svg_h;
        const invScale = 1 / zoomScale;
        const viewBoxX = (svgX - panX) * invScale;
        const viewBoxY = (svgY - panY) * invScale;
        const tileX = Math.round(viewBoxX / 16) * 16;
        const tileY = Math.round(viewBoxY / 16) * 16;
        lavaHighlight.setAttribute('x', tileX);
        lavaHighlight.setAttribute('y', tileY);
        lavaHighlight.style.display = 'block';
    }
});

document.addEventListener('mouseup', function(event) {
    if (lavaPlacementMode && dragStart) {
        if (selectRect.style.display !== 'none') {
            const rect = mapSvg.getBoundingClientRect();
            const invScale = 1 / zoomScale;
            const startSvgX = ((dragStart.x - rect.left) / rect.width) * svg_w;
            const startSvgY = ((dragStart.y - rect.top) / rect.height) * svg_h;
            const startViewX = (startSvgX - panX) * invScale;
            const startViewY = (startSvgY - panY) * invScale;
            const endSvgX = ((event.clientX - rect.left) / rect.width) * svg_w;
            const endSvgY = ((event.clientY - rect.top) / rect.height) * svg_h;
            const endViewX = (endSvgX - panX) * invScale;
            const endViewY = (endSvgY - panY) * invScale;
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
            const rect = mapSvg.getBoundingClientRect();
            const svgX = ((event.clientX - rect.left) / rect.width) * svg_w;
            const svgY = ((event.clientY - rect.top) / rect.height) * svg_h;
            const invScale = 1 / zoomScale;
            const viewBoxX = (svgX - panX) * invScale;
            const viewBoxY = (svgY - panY) * invScale;
            const tileX = Math.round(viewBoxX / 16) * 16;
            const tileY = Math.round(viewBoxY / 16) * 16;
            fetch('/api/lava', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ x: tileX, y: tileY })
            }).then(function(r) { return r.json(); }).then(function() {
            }).catch(function() {});
        }
        dragStart = null;
        selectRect.style.display = 'none';
        return;
    }
    if (!isPanning) return;
    isPanning = false;
    clickStart = null;
    mapSvg.classList.remove('grabbing');
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

zoomInBtn.addEventListener('click', function() { setZoom(1.15); });
zoomOutBtn.addEventListener('click', function() { setZoom(0.85); });
zoomResetBtn.addEventListener('click', function() { resetZoom(); });

function updateLavaToggle() {
    lavaPlacementMode = !lavaPlacementMode;
    toggleLavaBtn.classList.toggle('toggle-active', lavaPlacementMode);
    if (lavaPlacementMode) {
        lavaModeStatus.textContent = 'LAVA PLACEMENT MODE - click to place/remove zones';
        mapSvg.style.cursor = 'crosshair';
    } else {
        lavaModeStatus.textContent = '';
        mapSvg.style.cursor = '';
        lavaHighlight.style.display = 'none';
    }
}

toggleLavaBtn.addEventListener('click', updateLavaToggle);

if (lavaPlacementMode) {
    lavaModeStatus.textContent = 'LAVA PLACEMENT MODE - click to place/remove zones';
    mapSvg.style.cursor = 'crosshair';
}

tabBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
        tabBtns.forEach(function(b) { b.classList.remove('active'); });
        tabPanes.forEach(function(p) { p.classList.remove('active'); });
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

function updateMosaic() {
    fetch('/api/mosaic', { cache: 'no-store' })
        .then(function(r) {
            if (r.status === 204) {
                mosaicStatus.textContent = 'no stream';
                if (mosaicObjectUrl) {
                    URL.revokeObjectURL(mosaicObjectUrl);
                    mosaicObjectUrl = null;
                }
                mosaicImage.removeAttribute('src');
                return null;
            }
            return r.blob();
        })
        .then(function(blob) {
            if (!blob) return;
            if (mosaicObjectUrl) {
                URL.revokeObjectURL(mosaicObjectUrl);
            }
            mosaicObjectUrl = URL.createObjectURL(blob);
            mosaicImage.src = mosaicObjectUrl;
            mosaicStatus.textContent = 'live';
        })
        .catch(function() {
            mosaicStatus.textContent = 'offline';
        });
}

const dynamicMosaicLiveUpdate = document.getElementById('dynamic-mosaic-live-update');
const dynamicMosaicBandwidth = document.getElementById('dynamic-mosaic-bandwidth');

dynamicMosaicPageSize.addEventListener('input', function() {
    dynamicMosaicPageSizeVal = parseInt(this.value, 10);
    dynamicMosaicPageSizeValue.textContent = dynamicMosaicPageSizeVal.toString();
    dynamicMosaicCurrentPage = 0;
    if (document.getElementById('dynamic-mosaic-tab').classList.contains('active')) {
        const envCount = lastState.envs ? lastState.envs.length : 0;
        if (envCount > 0) {
            updateDynamicMosaic(envCount);
        }
    }
});

dynamicMosaicPrevBtn.addEventListener('click', function() {
    if (dynamicMosaicCurrentPage > 0) {
        dynamicMosaicCurrentPage--;
        if (document.getElementById('dynamic-mosaic-tab').classList.contains('active')) {
            const envCount = lastState.envs ? lastState.envs.length : 0;
            if (envCount > 0) {
                updateDynamicMosaic(envCount);
            }
        }
    }
});

dynamicMosaicNextBtn.addEventListener('click', function() {
    const envCount = lastState.envs ? lastState.envs.length : 0;
    const maxPage = Math.max(0, Math.ceil(envCount / dynamicMosaicPageSizeVal) - 1);
    if (dynamicMosaicCurrentPage < maxPage) {
        dynamicMosaicCurrentPage++;
        if (document.getElementById('dynamic-mosaic-tab').classList.contains('active')) {
            const envCount = lastState.envs ? lastState.envs.length : 0;
            if (envCount > 0) {
                updateDynamicMosaic(envCount);
            }
        }
    }
});

function updateDynamicMosaic(envCount) {
    const grid = document.getElementById('dynamic-mosaic-grid');
    if (!grid) return;

    const maxPage = Math.max(0, Math.ceil(envCount / dynamicMosaicPageSizeVal) - 1);
    if (dynamicMosaicCurrentPage > maxPage) {
        dynamicMosaicCurrentPage = maxPage;
    }
    const startIndex = dynamicMosaicCurrentPage * dynamicMosaicPageSizeVal;
    const endIndex = Math.min(startIndex + dynamicMosaicPageSizeVal, envCount);
    const visibleCount = endIndex - startIndex;

    dynamicMosaicPageIndicator.textContent = 'Page ' + (dynamicMosaicCurrentPage + 1) + ' of ' + (maxPage + 1);

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
    dynamicMosaicStatus.textContent = 'live (' + envCount + ' streams, showing ' + visibleCount + ')';
}

function calculateBandwidth() {
    const now = Date.now();
    const timeDiff = (now - lastBandwidthTime) / 1000;
    if (timeDiff < 1) return;

    const visibleEnvs = parseInt(document.getElementById('dynamic-mosaic-page-size').value, 10);
    const isLive = document.getElementById('dynamic-mosaic-live-update').checked;
    if (!isLive) {
        dynamicMosaicBandwidth.textContent = 'Bandwidth: Paused';
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
    dynamicMosaicBandwidth.textContent = 'Bandwidth: ~' + bandwidthStr;
}

function selectInspectorEnv(envIndex) {
    selectedInspectorEnv = envIndex;
    inspectorEnvSelect.value = envIndex.toString();
    updateInspectorScreen();
    fetchInspectorData();
    updateSelectionHighlight();
}

function updateSelectionHighlight() {
    document.querySelectorAll('.dynamic-mosaic-cell').forEach(function(cell, idx) {
        if (idx === selectedInspectorEnv) {
            cell.style.borderColor = 'var(--accent)';
            cell.style.boxShadow = '0 0 12px rgba(110, 231, 255, 0.4)';
        } else {
            cell.style.borderColor = 'rgba(255,255,255,0.08)';
            cell.style.boxShadow = 'none';
        }
    });

    const envs = lastState.envs || [];
    const selectedEnv = envs.find(e => e.env_index === selectedInspectorEnv);
    if (selectedEnv && selectedEnv.x !== undefined) {
        selectRect.setAttribute('x', selectedEnv.x - 8);
        selectRect.setAttribute('y', selectedEnv.y - 8);
        selectRect.setAttribute('width', 16);
        selectRect.setAttribute('height', 16);
        selectRect.style.display = 'block';
    } else {
        selectRect.style.display = 'none';
    }
}

function updateInspectorScreen() {
    const img = document.getElementById('inspector-screen');
    if (!img) return;

    const newUrl = '/api/inspector-screen?env=' + selectedInspectorEnv + '&t=' + Date.now();
    if (inspectorObjectUrl) {
        URL.revokeObjectURL(inspectorObjectUrl);
    }

    fetch(newUrl, { cache: 'no-store' })
        .then(function(r) {
            if (r.status === 204) {
                img.removeAttribute('src');
                return null;
            }
            return r.blob();
        })
        .then(function(blob) {
            if (!blob) return;
            inspectorObjectUrl = URL.createObjectURL(blob);
            img.src = inspectorObjectUrl;
        })
        .catch(function() {});
}

inspectorEnvSelect.addEventListener('change', function() {
    selectedInspectorEnv = parseInt(this.value) || 0;
    updateInspectorScreen();
    fetchInspectorData();
});

update();
setInterval(update, 500);

setInterval(function() {
    if (document.getElementById('dynamic-mosaic-tab').classList.contains('active')) {
        const isLive = document.getElementById('dynamic-mosaic-live-update').checked;
        if (isLive) {
            const envCount = lastState.envs ? lastState.envs.length : 0;
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
