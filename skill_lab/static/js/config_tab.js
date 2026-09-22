import { el, state } from './state.js';

const ACTION_NAMES = ['Down', 'Left', 'Right', 'Up', 'A', 'B', 'Start', 'Select'];

function initConfig() {
  if (el.maxStepsSlider) {
    el.maxStepsSlider.addEventListener('input', function() {
      el.maxStepsValue.textContent = String(el.maxStepsSlider.value);
    });
  }

  initControlBindings();

  if (el.applyConfigBtn) {
    el.applyConfigBtn.addEventListener('click', function() {
      const payload = {
        max_steps: parseInt(el.maxStepsSlider.value, 10),
        save_on_catch: el.saveOnCatchCheckbox.checked,
        gamepad_bindings: state.gamepadBindings,
        key_bindings: state.keyBindings,
      };
      el.configStatus.textContent = 'saving...';
      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function(r) { return r.json(); })
        .then(function(data) {
          el.configStatus.textContent = data.status || 'saved';
        })
        .catch(function() {
          el.configStatus.textContent = 'error';
        });
    });
  }
}

function initControlBindings() {
  fetch('/api/control', { cache: 'no-store' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      state.gamepadBindings = data.gamepad_bindings || {};
      state.keyBindings = data.key_bindings || {};
      renderGamepadBindings();
      renderKeyBindings();
    })
    .catch(function() {
      renderGamepadBindings();
      renderKeyBindings();
    });
}

function renderGamepadBindings() {
  if (!el.gamepadBindingsBody) return;
  let html = '';
  for (const action of ACTION_NAMES) {
    const binding = state.gamepadBindings[action] || '';
    const display = binding || '-';
    const isCapturing = state.captureAction === action && state.captureType === 'gamepad';
    html += '<tr>';
    html += '<td class="binding-action">' + action + '</td>';
    html += '<td class="binding-value">' + (isCapturing ? 'waiting...' : display) + '</td>';
    html += '<td><button class="binding-set-btn" data-action="' + action + '" data-type="gamepad">' + (isCapturing ? 'cancel' : 'Set') + '</button></td>';
    html += '</tr>';
  }
  el.gamepadBindingsBody.innerHTML = html;

  el.gamepadBindingsBody.querySelectorAll('.binding-set-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      const action = this.getAttribute('data-action');
      const type = this.getAttribute('data-type');
      if (state.captureAction === action && state.captureType === type) {
        stopCapture();
      } else {
        startGamepadCapture(action);
      }
    });
  });
}

function renderKeyBindings() {
  if (!el.keyboardBindingsBody) return;
  let html = '';
  for (const action of ACTION_NAMES) {
    const binding = state.keyBindings[action] || '';
    const display = binding ? binding.toUpperCase() : '-';
    const isCapturing = state.captureAction === action && state.captureType === 'keyboard';
    html += '<tr>';
    html += '<td class="binding-action">' + action + '</td>';
    html += '<td class="binding-value">' + (isCapturing ? 'waiting...' : display) + '</td>';
    html += '<td><button class="binding-set-btn" data-action="' + action + '" data-type="keyboard">' + (isCapturing ? 'cancel' : 'Set') + '</button></td>';
    html += '</tr>';
  }
  el.keyboardBindingsBody.innerHTML = html;

  el.keyboardBindingsBody.querySelectorAll('.binding-set-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      const action = this.getAttribute('data-action');
      const type = this.getAttribute('data-type');
      if (state.captureAction === action && state.captureType === type) {
        stopCapture();
      } else {
        startKeyboardCapture(action);
      }
    });
  });
}

function stopCapture() {
  state.captureAction = null;
  state.captureType = null;
  renderGamepadBindings();
  renderKeyBindings();
  stopGamepadCapturePolling();
  stopKeyboardCapture();
}

function startGamepadCapture(action) {
  state.captureAction = action;
  state.captureType = 'gamepad';
  renderGamepadBindings();
  _pollForGamepadInput();
}

function _pollForGamepadInput() {
  if (state.captureAction === null || state.captureType !== 'gamepad') return;
  const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
  const pad = gamepads[0];
  if (pad) {
    for (let i = 0; i < pad.buttons.length; i++) {
      if (pad.buttons[i].pressed) {
        state.gamepadBindings[state.captureAction] = 'button:' + i;
        stopCapture();
        return;
      }
    }
  }
  state._gamepadCaptureId = setTimeout(_pollForGamepadInput, 50);
}

function stopGamepadCapturePolling() {
  if (state._gamepadCaptureId !== undefined) {
    clearTimeout(state._gamepadCaptureId);
    state._gamepadCaptureId = undefined;
  }
}

function startKeyboardCapture(action) {
  state.captureAction = action;
  state.captureType = 'keyboard';
  renderKeyBindings();
  document.addEventListener('keydown', _onCaptureKeyDown, true);
}

function _onCaptureKeyDown(e) {
  if (state.captureAction === null || state.captureType !== 'keyboard') return;
  const code = e.code;
  const token = _codeToSdlToken(code);
  state.keyBindings[state.captureAction] = token;
  stopCapture();
}

function stopKeyboardCapture() {
  document.removeEventListener('keydown', _onCaptureKeyDown, true);
}

function _codeToSdlToken(code) {
  const map = {
    ArrowDown: 'down', ArrowUp: 'up', ArrowLeft: 'left', ArrowRight: 'right',
    Enter: 'return', Tab: 'tab', PageUp: 'pageup', PageDown: 'pagedown',
    Escape: 'escape', Space: ' ',
  };
  if (code in map) return map[code];
  if (code.startsWith('Key')) return code.slice(3).toLowerCase();
  if (code.startsWith('Digit')) return code.slice(5);
  return code.toLowerCase();
}

export { initConfig, initControlBindings };
