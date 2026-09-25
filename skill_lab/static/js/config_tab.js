import { el, state } from './state.js';

const ACTION_NAMES = ['Down', 'Left', 'Right', 'Up', 'A', 'B', 'Start', 'Select'];

function initConfig() {
  if (el.maxStepsSlider) {
    el.maxStepsSlider.addEventListener('input', function() {
      el.maxStepsValue.textContent = String(el.maxStepsSlider.value);
    });
    if (el.extraStepsSlider && el.extraStepsValue) {
      el.extraStepsSlider.addEventListener('input', function() {
        el.extraStepsValue.textContent = String(el.extraStepsSlider.value);
      });
      el.extraStepsValue.textContent = String(el.extraStepsSlider.value);
    }
  }

  initControlBindings();

  if (el.applyConfigBtn) {
    el.applyConfigBtn.addEventListener('click', function() {
      const payload = {
        max_steps: parseInt(el.maxStepsSlider.value, 10),
        extra_steps: parseInt(el.extraStepsSlider ? el.extraStepsSlider.value : 0, 10),
        save_on_catch: el.saveOnCatchCheckbox.checked,
        web_gamepad_bindings: state.webGamepadBindings,
        web_key_bindings: state.webKeyBindings,
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
      state.webGamepadBindings = data.web_gamepad_bindings || {};
      state.webKeyBindings = data.web_key_bindings || {};
      renderWebGamepadBindings();
      renderWebKeyBindings();
    })
    .catch(function() {
      renderWebGamepadBindings();
      renderWebKeyBindings();
    });

  // Load the runtime config snapshot (extra_steps, max_steps overrides, etc.)
  // so the sliders reflect what the running train loop has applied.
  fetch('/api/config', { cache: 'no-store' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.extra_steps !== undefined && el.extraStepsSlider) {
        el.extraStepsSlider.value = String(data.extra_steps);
        if (el.extraStepsValue) el.extraStepsValue.textContent = String(data.extra_steps);
      }
      if (data.max_steps !== null && data.max_steps !== undefined && el.maxStepsSlider) {
        el.maxStepsSlider.value = String(data.max_steps);
        if (el.maxStepsValue) el.maxStepsValue.textContent = String(data.max_steps);
      }
      state.runtimeConfig = data;
    })
    .catch(function() {});
}

function renderWebGamepadBindings() {
  if (!el.webGamepadBindingsBody) return;
  let html = '';
  for (const action of ACTION_NAMES) {
    const binding = state.webGamepadBindings[action] || '';
    const display = binding || '-';
    const isCapturing = state.captureAction === action && state.captureType === 'web_gamepad';
    html += '<tr>';
    html += '<td class="binding-action">' + action + '</td>';
    html += '<td class="binding-value">' + (isCapturing ? 'waiting...' : display) + '</td>';
    html += '<td><button class="binding-set-btn" data-action="' + action + '" data-type="web_gamepad">' + (isCapturing ? 'cancel' : 'Set') + '</button></td>';
    html += '</tr>';
  }
  el.webGamepadBindingsBody.innerHTML = html;

  el.webGamepadBindingsBody.querySelectorAll('.binding-set-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      const action = this.getAttribute('data-action');
      const type = this.getAttribute('data-type');
      if (state.captureAction === action && state.captureType === type) {
        stopWebCapture();
      } else {
        startWebGamepadCapture(action);
      }
    });
  });
}

function renderWebKeyBindings() {
  if (!el.webKeyboardBindingsBody) return;
  let html = '';
  for (const action of ACTION_NAMES) {
    const binding = state.webKeyBindings[action] || '';
    const display = binding ? binding.toUpperCase() : '-';
    const isCapturing = state.captureAction === action && state.captureType === 'web_keyboard';
    html += '<tr>';
    html += '<td class="binding-action">' + action + '</td>';
    html += '<td class="binding-value">' + (isCapturing ? 'waiting...' : display) + '</td>';
    html += '<td><button class="binding-set-btn" data-action="' + action + '" data-type="web_keyboard">' + (isCapturing ? 'cancel' : 'Set') + '</button></td>';
    html += '</tr>';
  }
  el.webKeyboardBindingsBody.innerHTML = html;

  el.webKeyboardBindingsBody.querySelectorAll('.binding-set-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      const action = this.getAttribute('data-action');
      const type = this.getAttribute('data-type');
      if (state.captureAction === action && state.captureType === type) {
        stopWebCapture();
      } else {
        startWebKeyboardCapture(action);
      }
    });
  });
}

function stopWebCapture() {
  state.captureAction = null;
  state.captureType = null;
  renderWebGamepadBindings();
  renderWebKeyBindings();
  stopWebGamepadCapturePolling();
  stopWebKeyboardCapture();
}

function startWebGamepadCapture(action) {
  state.captureAction = action;
  state.captureType = 'web_gamepad';
  renderWebGamepadBindings();
  pollForWebGamepadInput();
}

function pollForWebGamepadInput() {
  if (state.captureAction === null || state.captureType !== 'web_gamepad') return;
  const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
  const pad = gamepads[0];
  if (pad) {
    for (let i = 0; i < pad.buttons.length; i++) {
      if (pad.buttons[i].pressed) {
        state.webGamepadBindings[state.captureAction] = 'button:' + i;
        stopWebCapture();
        return;
      }
    }
    for (let i = 0; i < pad.axes.length; i++) {
      const val = pad.axes[i];
      if (Math.abs(val) > 0.5) {
        const direction = val > 0 ? 'positive' : 'negative';
        state.webGamepadBindings[state.captureAction] = 'axis:' + i + ':' + direction;
        stopWebCapture();
        return;
      }
    }
  }
  state._webGamepadCaptureId = setTimeout(pollForWebGamepadInput, 50);
}

function stopWebGamepadCapturePolling() {
  if (state._webGamepadCaptureId !== undefined) {
    clearTimeout(state._webGamepadCaptureId);
    state._webGamepadCaptureId = undefined;
  }
}

function startWebKeyboardCapture(action) {
  state.captureAction = action;
  state.captureType = 'web_keyboard';
  renderWebKeyBindings();
  document.addEventListener('keydown', onWebCaptureKeyDown, true);
}

function stopWebKeyboardCapture() {
  document.removeEventListener('keydown', onWebCaptureKeyDown, true);
}

function onWebCaptureKeyDown(e) {
  if (state.captureAction === null || state.captureType !== 'web_keyboard') return;
  const code = e.code;
  const token = codeToSdlToken(code);
  state.webKeyBindings[state.captureAction] = token;
  stopWebCapture();
}

function codeToSdlToken(code) {
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
