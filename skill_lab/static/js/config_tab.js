import { el } from './state.js';

function initConfig() {
  if (el.maxStepsSlider) {
    el.maxStepsSlider.addEventListener('input', function() {
      el.maxStepsValue.textContent = String(el.maxStepsSlider.value);
    });
  }

  if (el.applyConfigBtn) {
    el.applyConfigBtn.addEventListener('click', function() {
      const payload = {
        max_steps: parseInt(el.maxStepsSlider.value, 10),
        save_on_catch: el.saveOnCatchCheckbox.checked,
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

export { initConfig };
