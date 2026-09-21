import { el, state } from './state.js';
import { isInspectorTabActive } from './util.js';

function renderInspectorDetails(data) {
  if (!el.inspectorDetails) return;

  if (!data || data.error) {
    el.inspectorDetails.innerHTML = '<div style="color: #ff6b6b; padding: 12px;">' +
      (data && data.error ? 'Error: ' + data.error : 'No data available') +
      '</div>';
    return;
  }

  state.lastInspectorData = data;
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

  el.inspectorDetails.innerHTML = html;
}

function renderInspectorMemoryWatch(data) {
  if (!el.inspectorMemoryBody) return;
  el.inspectorMemoryBody.innerHTML = '';
  if (!data || !data.memory_watch || !Array.isArray(data.memory_watch)) {
    if (el.inspectorStatus) el.inspectorStatus.textContent = 'offline';
    return;
  }
  data.memory_watch.forEach(function(entry) {
    const cls = entry.changed ? ' changed' : '';
    const row = '<tr class="' + cls + '">' +
      '<td>0x' + entry.address.toString(16).toUpperCase().padStart(4, '0') + '</td>' +
      '<td>' + (entry.value !== undefined && entry.value !== null ? entry.value : '-') + '</td>' +
      '<td>' + (entry.description || '') + '</td>' +
      '</tr>';
    el.inspectorMemoryBody.insertAdjacentHTML('beforeend', row);
  });
  if (el.inspectorStatus) el.inspectorStatus.textContent = 'live';
}

function renderInspector(data) {
  renderInspectorDetails(data);
  renderInspectorMemoryWatch(data);
}

function fetchInspectorData() {
  const idx = state.selectedInspectorEnv;
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
      if (el.inspectorStatus) el.inspectorStatus.textContent = 'offline';
    });
}

function updateSelectionHighlight() {
  document.querySelectorAll('.dynamic-mosaic-cell').forEach(function(cell, idx) {
    if (idx === state.selectedInspectorEnv) {
      cell.style.borderColor = 'var(--accent)';
      cell.style.boxShadow = '0 0 12px rgba(110, 231, 255, 0.4)';
    } else {
      cell.style.borderColor = 'rgba(255,255,255,0.08)';
      cell.style.boxShadow = 'none';
    }
  });

  const envs = state.lastState.envs || [];
  const selectedEnv = envs.find(e => e.env_index === state.selectedInspectorEnv);
  if (selectedEnv && selectedEnv.x !== undefined) {
    if (state.selectRect) {
      state.selectRect.setAttribute('x', selectedEnv.x - 8);
      state.selectRect.setAttribute('y', selectedEnv.y - 8);
      state.selectRect.setAttribute('width', 16);
      state.selectRect.setAttribute('height', 16);
      state.selectRect.style.display = 'block';
    }
  } else {
    if (state.selectRect) state.selectRect.style.display = 'none';
  }
}

function selectInspectorEnv(envIndex) {
  state.selectedInspectorEnv = envIndex;
  el.inspectorEnvSelect.value = envIndex.toString();
  updateInspectorScreen();
  fetchInspectorData();
  updateSelectionHighlight();
}

function updateInspectorScreen() {
  const img = el.inspectorScreen;
  if (!img) return;

  const newUrl = '/api/inspector-screen?env=' + state.selectedInspectorEnv + '&t=' + Date.now();
  if (state.inspectorObjectUrl) {
    URL.revokeObjectURL(state.inspectorObjectUrl);
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
      state.inspectorObjectUrl = URL.createObjectURL(blob);
      img.src = state.inspectorObjectUrl;
    })
    .catch(function() {});
}

function updateInspectorSelect(envs) {
  const currentVal = el.inspectorEnvSelect.value;
  el.inspectorEnvSelect.innerHTML = envs.map(function(env) {
    return '<option value="' + env.env_index + '">Env ' + (env.env_index + 1) + ' - HP: ' + (env.hp * 100).toFixed(0) + '%</option>';
  }).join('');
  if (currentVal !== '' && envs.some(e => e.env_index == currentVal)) {
    el.inspectorEnvSelect.value = currentVal;
  }
  state.selectedInspectorEnv = parseInt(el.inspectorEnvSelect.value) || 0;
}

function initInspector() {
  el.inspectorEnvSelect.addEventListener('change', function() {
    state.selectedInspectorEnv = parseInt(this.value) || 0;
    updateInspectorScreen();
    fetchInspectorData();
  });

  if (el.inspectorStatus) el.inspectorStatus.textContent = 'idle';
}

export {
  initInspector,
  updateInspectorSelect,
  fetchInspectorData,
  updateInspectorScreen,
  selectInspectorEnv,
  renderInspector,
  renderInspectorDetails,
  renderInspectorMemoryWatch,
  updateSelectionHighlight,
};
