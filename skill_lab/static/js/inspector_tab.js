import { el, state } from './state.js';
import { isInspectorTabActive } from './util.js';

const ACTION_NAMES = ['Down', 'Left', 'Right', 'Up', 'A', 'B', 'Start', 'Select'];

const SDL_TO_CODE_MAP = {
  'down': 'ArrowDown',
  'up': 'ArrowUp',
  'left': 'ArrowLeft',
  'right': 'ArrowRight',
  'return': 'Enter',
  'tab': 'Tab',
  'pageup': 'PageUp',
  'pagedown': 'PageDown',
  'escape': 'Escape',
  ' ': 'Space',
  'p': 'KeyP',
  'z': 'KeyZ',
  'x': 'KeyX',
};

function resolveGamepadToken(token) {
  if (!token) return null;
  const m = token.match(/^(?:controller|button):(\d+)$/);
  if (m) return { type: 'button', index: parseInt(m[1]) };
  const ax = token.match(/^axis:(\d+):(positive|negative)$/);
  if (ax) return { type: 'axis', index: parseInt(ax[1]), direction: ax[2] };
  return null;
}

function resolveKeyToken(token) {
  if (!token) return null;
  if (SDL_TO_CODE_MAP[token]) return SDL_TO_CODE_MAP[token];
  if (token.length === 1 && token >= 'a' && token <= 'z') return 'Key' + token.toUpperCase();
  if (token.length === 1 && token >= '0' && token <= '9') return 'Digit' + token;
  return token.replace(/^key/, 'Key').replace(/^arrow/, 'Arrow');
}

function initInspector() {
  el.inspectorEnvSelect.addEventListener('change', function() {
    state.selectedInspectorEnv = parseInt(this.value) || 0;
    updateInspectorScreen();
    fetchInspectorData();
    if (state.controlActive) {
      fetchControlToggle();
    }
  });

  if (el.inspectorControlBtn) {
    el.inspectorControlBtn.addEventListener('click', toggleInspectorControl);
  }

  if (el.inspectorDetailsToggle) {
    el.inspectorDetailsToggle.addEventListener('click', toggleInspectorDetails);
  }

  state.inspectorDetailsCollapsed = true;

  if (el.inspectorStatus) el.inspectorStatus.textContent = 'idle';
}

function fetchControlState() {
  fetch('/api/control', { cache: 'no-store' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      state.gamepadBindings = data.gamepad_bindings || {};
      state.keyBindings = data.key_bindings || {};
      state.controlActive = data.control_active || false;
      state.controlEnvIndex = data.env_index || 0;
      updateControlButton(data.control_active || false);
      if (data.control_active) {
        startGamepadPolling();
        startKeyboardListening();
      }
    })
    .catch(function() {
      updateControlButton(false);
    });
}

function fetchControlToggle() {
  const payload = {
    toggle: state.controlActive,
    env: state.selectedInspectorEnv,
  };
  fetch('/api/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(function() {});
}

function toggleInspectorControl() {
  state.controlActive = !state.controlActive;
  updateControlButton(state.controlActive);
  fetchControlToggle();
  if (state.controlActive) {
    startGamepadPolling();
    startKeyboardListening();
  } else {
    stopGamepadPolling();
    stopKeyboardListening();
    state.gamepadButtonStates = {};
  }
}

function updateControlButton(active) {
  if (el.inspectorControlBtn) {
    el.inspectorControlBtn.textContent = active ? 'Release Control' : 'Take Control';
    el.inspectorControlBtn.classList.toggle('control-active', active);
  }
}

function startGamepadPolling() {
  if (state.gamepadPollId !== null) return;
  state.gamepadPollId = setInterval(pollGamepad, 16);
}

function stopGamepadPolling() {
  if (state.gamepadPollId !== null) {
    clearInterval(state.gamepadPollId);
    state.gamepadPollId = null;
  }
}

function pollGamepad() {
  if (!state.controlActive) return;
  const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
  const pad = gamepads[0];
  if (!pad) return;
  for (const action of ACTION_NAMES) {
    const token = state.gamepadBindings[action];
    if (!token) continue;
    const resolved = resolveGamepadToken(token);
    if (!resolved) continue;
    let pressed = false;
    if (resolved.type === 'button') {
      if (resolved.index < pad.buttons.length) {
        pressed = !!pad.buttons[resolved.index].pressed;
      }
    } else if (resolved.type === 'axis') {
      if (resolved.index < pad.axes.length) {
        const val = pad.axes[resolved.index];
        pressed = resolved.direction === 'positive' ? val > 0.5 : val < -0.5;
      }
    }
    const prevPressed = state.gamepadButtonStates[token] || false;
    if (pressed !== prevPressed) {
      state.gamepadButtonStates[token] = pressed;
      sendInput(action, pressed);
    }
  }
}

function onKeyDown(e) {
  if (!state.controlActive) return;
  if (e.repeat) return;
  for (const action of ACTION_NAMES) {
    const token = state.keyBindings[action];
    if (!token) continue;
    const code = resolveKeyToken(token);
    if (!code) continue;
    if (e.code === code && !state.keyStates[code]) {
      state.keyStates[code] = true;
      e.preventDefault();
      sendInput(action, true);
    }
  }
}

function onKeyUp(e) {
  if (!state.controlActive) return;
  for (const action of ACTION_NAMES) {
    const token = state.keyBindings[action];
    if (!token) continue;
    const code = resolveKeyToken(token);
    if (!code) continue;
    if (e.code === code && state.keyStates[code]) {
      state.keyStates[code] = false;
      e.preventDefault();
      sendInput(action, false);
    }
  }
}

function startKeyboardListening() {
  document.addEventListener('keydown', onKeyDown, true);
  document.addEventListener('keyup', onKeyUp, true);
}

function stopKeyboardListening() {
  document.removeEventListener('keydown', onKeyDown, true);
  document.removeEventListener('keyup', onKeyUp, true);
  state.keyStates = {};
}

function sendInput(action, pressed) {
  fetch('/api/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action: action,
      pressed: pressed,
      env: state.selectedInspectorEnv,
    }),
  }).catch(function() {});
}

function toggleInspectorDetails() {
  state.inspectorDetailsCollapsed = !state.inspectorDetailsCollapsed;
  if (el.inspectorDetails) {
    if (state.inspectorDetailsCollapsed) {
      el.inspectorDetails.classList.remove('inspector-details-expanded');
      el.inspectorDetails.classList.add('inspector-details-collapsed');
    } else {
      el.inspectorDetails.classList.remove('inspector-details-collapsed');
      el.inspectorDetails.classList.add('inspector-details-expanded');
    }
  }
  if (el.inspectorDetailsToggle) {
    var icon = el.inspectorDetailsToggle.querySelector('.toggle-icon');
    if (icon) icon.classList.toggle('collapsed', state.inspectorDetailsCollapsed);
  }
}

function renderPartyTable(party, showDVs) {
  if (!party || party.length === 0) {
    return '<div style="color: #8aa0c7; font-size: 0.85rem;">No Pok&eacute;mon available</div>';
  }
  let t = '<table class="inspector-table party-table">';
  if (showDVs !== false) {
    t += '<thead><tr><th>#</th><th>Nickname</th><th>Species</th><th>Lv</th><th>HP</th><th>Types</th><th>DVs (Atk/Def/Spe/SpA)</th><th>Shiny</th></tr></thead>';
  } else {
    t += '<thead><tr><th>#</th><th>Species</th><th>Lv</th><th>HP</th></tr></thead>';
  }
  t += '<tbody>';
  for (let i = 0; i < party.length; i++) {
    const p = party[i];
    t += '<tr>';
    t += '<td>' + (i + 1) + '</td>';
    if (showDVs !== false) {
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
      t += '<td>' + nickname + '</td>';
      t += '<td>' + species + '</td>';
      t += '<td>' + level + '</td>';
      t += '<td>' + hp + '/' + maxHp + '</td>';
      t += '<td>' + type1 + type2 + '</td>';
      t += '<td>' + dvStr + '</td>';
      t += '<td>' + shinyStr + '</td>';
    } else {
      const species = p.speciesName || p.nickname || '?';
      const level = p.level || 0;
      const hp = (p.curHP !== undefined ? p.curHP : '?');
      const maxHp = (p.maxHP !== undefined ? p.maxHP : '?');
      t += '<td>' + species + '</td>';
      t += '<td>' + level + '</td>';
      t += '<td>' + hp + '/' + maxHp + '</td>';
    }
    t += '</tr>';
  }
  t += '</tbody></table>';
  return t;
}

function renderMilestones(data) {
  const checkpointsData = data.checkpoints || {};
  const checkpoints = checkpointsData.checkpoints || [];
  if (!el.inspectorMilestones) return;
  if (!checkpoints.length) {
    el.inspectorMilestones.innerHTML = '<div style="color: #8aa0c7; font-size: 0.8rem; padding: 4px 0;">No milestones configured</div>';
    return;
  }
  let html = '';
  const currentIdx = checkpointsData.current_target_index || 0;
  checkpoints.forEach(function(cp, idx) {
    const achieved = cp.achieved || false;
    const isCurrent = idx === currentIdx && !achieved;
    let cls = 'milestone-pending';
    let label = '';
    if (achieved) {
      cls = 'milestone-done';
      label = '✓';
    } else if (isCurrent) {
      cls = 'milestone-current';
      label = '▶';
    }
    const step = cp.achieved_step ? ' @ s' + cp.achieved_step : '';
    html += '<div class="milestone-item ' + cls + '">';
    html += '<span class="milestone-name">' + label + ' ' + (cp.name || 'unnamed') + '</span>';
    html += '<span class="milestone-step">' + step + '</span>';
    html += '</div>';
  });
  el.inspectorMilestones.innerHTML = html;
}

function renderInspectorDetails(data) {
  if (!el.inspectorDetails) return;

  if (!data || data.error) {
    el.inspectorDetails.innerHTML = '<div style="color: #ff6b6b; padding: 12px;">' +
      (data && data.error ? 'Error: ' + data.error : 'No data available') +
      '</div>';
    return;
  }

  state.lastInspectorData = data;

  // ---- Render world info inline in header ----
  const stats = data.stats || {};
  const mapId = stats.map_id || 0;
  if (el.inspectorWorldInfo) {
    el.inspectorWorldInfo.innerHTML =
      'Map: <span class="val">0x' + mapId.toString(16).toUpperCase().padStart(2, '0') + '</span>' +
      ' X: <span class="val">' + (stats.x ?? 0) + '</span>' +
      ' Y: <span class="val">' + (stats.y ?? 0) + '</span>';
  }

  // ---- Render milestones under the screen ----
  renderMilestones(data);

  // ---- Render player party ----
  const party = Array.isArray(data.party) ? data.party : [];
  if (el.inspectorParty) {
    el.inspectorParty.innerHTML = renderPartyTable(party, true);
  }

  // ---- Render opponent party ----
  const opponent = Array.isArray(data.opponent) ? data.opponent : [];
  if (el.inspectorOpponent) {
    el.inspectorOpponent.innerHTML = renderPartyTable(opponent, false);
  }

  // ---- Build collapsible details (everything else) ----
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
  var fledCount = stats.fled_battle || 0;
  var fledClass = fledCount > 0 ? 'stat-danger' : '';
  html += '<tr><td class="inspect-label">Fled Battles</td><td class="' + fledClass + '">' + fledCount + '</td></tr>';
  html += '<tr><td class="inspect-label">Wall Collisions</td><td>' + (stats.walls || 0) + '</td></tr>';
  html += '</table>';
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

  // ---- Reward History ----
  const rewardHistory = data.reward_history || {};
  const rewardCounts = rewardHistory.counts || {};
  const rewardEvents = Array.isArray(rewardHistory.events) ? rewardHistory.events : [];
  const totalFled = rewardCounts.fled_battle || 0;
  html += '<div class="inspector-section">';
  html += '<h3>Reward History</h3>';
  if (rewardEvents.length === 0 && Object.keys(rewardCounts).length === 0) {
    html += '<div style="color: #8aa0c7; font-size: 0.85rem;">No rewards recorded yet</div>';
  } else {
    html += '<table class="inspector-table">';
    html += '<tr><td class="inspect-label">Fled Battles</td><td class="' + (totalFled > 0 ? 'stat-danger' : '') + '">' + totalFled + '</td></tr>';
    html += '<tr><td class="inspect-label">Trainer Wins</td><td>' + (rewardCounts.combat_trainer || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Wild Wins</td><td>' + (rewardCounts.combat_wild || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Milestones</td><td>' + (rewardCounts.milestone || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Events</td><td>' + (rewardCounts.event || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Map Discovers</td><td>' + (rewardCounts.map_discovery || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Heals</td><td>' + (rewardCounts.healing || 0) + '</td></tr>';
    html += '<tr><td class="inspect-label">Breadcrumbs</td><td>' + (rewardCounts.breadcrumb || 0) + '</td></tr>';
    html += '</table>';
    if (rewardEvents.length > 0) {
      html += '<div style="margin-top: 8px; font-size: 0.75rem; color: #aaa;">Recent events:</div>';
      html += '<div class="reward-event-list">';
      var recent = rewardEvents.slice(-10).reverse();
      for (var i = 0; i < recent.length; i++) {
        var evt = recent[i];
        var amt = evt.amount !== undefined ? evt.amount : 0;
        var evtClass = amt < 0 ? 'reward-negative' : 'reward-positive';
        var evtType = evt.type || '?';
        var evtStep = evt.step !== undefined ? evt.step : 0;
        var evtDesc = evt.description || '';
        html += '<div class="reward-event ' + evtClass + '">';
        html += '<span class="reward-type">' + evtType + '</span>';
        html += '<span class="reward-amount">' + (amt >= 0 ? '+' : '') + amt.toFixed(2) + '</span>';
        html += '<span class="reward-step">s' + evtStep + '</span>';
        if (evtDesc) html += '<span class="reward-desc">' + evtDesc + '</span>';
        html += '</div>';
      }
      html += '</div>';
    }
  }
  html += '</div>';

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
  fetchControlState,
  toggleInspectorControl,
  sendInput,
};
