const ext = typeof browser !== 'undefined' ? browser : chrome;

const MODE_DESCRIPTIONS = {
  off: 'Сайт видит всё. Для банков и сайтов, которые сломались',
  normal: 'Сайт не видит смену вкладки, фокус и вставку текста',
  strict: 'Ещё скрыты движения мыши, прокрутка и выделение. Некоторые сайты могут сломаться',
};

const MODE_NAMES = {
  off: 'Выключен',
  normal: 'Обычный',
  strict: 'Строгий',
};

let currentTabId = null;
let currentTabHost = null;
let targetSiteHost = null;
let currentMode = 'normal';
let isHttpPage = false;

const siteHostEl = document.getElementById('site-host');
const unsupportedEl = document.getElementById('unsupported');
const siteControlsEl = document.getElementById('site-controls');
const modeButtons = document.querySelectorAll('.mode-btn');
const modeDescEl = document.getElementById('mode-desc');
const reloadBtn = document.getElementById('reload-btn');
const unloadSelect = document.getElementById('unload-select');
const exceptionsSection = document.getElementById('exceptions-section');
const exceptionsList = document.getElementById('exceptions-list');
const errorMsgEl = document.getElementById('error-message');

function showError() {
  if (errorMsgEl) errorMsgEl.hidden = false;
}

function hideError() {
  if (errorMsgEl) errorMsgEl.hidden = true;
}

function updateModeUI(mode) {
  currentMode = mode;
  modeButtons.forEach((btn) => {
    const btnMode = btn.dataset.mode;
    btn.setAttribute('aria-pressed', btnMode === mode ? 'true' : 'false');
  });
  if (modeDescEl) {
    modeDescEl.textContent = MODE_DESCRIPTIONS[mode] || '';
  }
}

async function loadSiteStatus() {
  if (!isHttpPage || !currentTabHost) return;
  try {
    const res = await ext.runtime.sendMessage({
      type: 'get-site',
      host: currentTabHost,
    });
    if (!res || typeof res.mode !== 'string') {
      showError();
      return;
    }
    targetSiteHost = res.host || currentTabHost;
    updateModeUI(res.mode);
  } catch (err) {
    showError();
  }
}

function renderExceptions(sites) {
  const hosts = Object.keys(sites);
  if (hosts.length === 0) {
    exceptionsSection.hidden = true;
    exceptionsList.innerHTML = '';
    return;
  }

  exceptionsList.innerHTML = '';
  hosts.forEach((host) => {
    const mode = sites[host];
    const li = document.createElement('li');
    li.className = 'exception-item';

    const info = document.createElement('div');
    info.className = 'exception-info';

    const hostSpan = document.createElement('span');
    hostSpan.className = 'exception-host';
    hostSpan.textContent = host;
    hostSpan.title = host;

    const modeSpan = document.createElement('span');
    modeSpan.className = 'exception-mode';
    modeSpan.textContent = MODE_NAMES[mode] || mode;

    info.appendChild(hostSpan);
    info.appendChild(modeSpan);

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn-remove';
    removeBtn.textContent = 'Убрать';
    removeBtn.dataset.host = host;

    li.appendChild(info);
    li.appendChild(removeBtn);
    exceptionsList.appendChild(li);
  });

  exceptionsSection.hidden = false;
}

async function loadSettings() {
  try {
    const settings = await ext.runtime.sendMessage({ type: 'get-settings' });
    if (!settings) {
      showError();
      return;
    }
    if (typeof settings.unloadMinutes === 'number') {
      const valStr = String(settings.unloadMinutes);
      const exists = Array.from(unloadSelect.options).some((opt) => opt.value === valStr);
      if (!exists) {
        const customOpt = document.createElement('option');
        customOpt.value = valStr;
        customOpt.textContent = `${settings.unloadMinutes} минут`;
        unloadSelect.appendChild(customOpt);
      }
      unloadSelect.value = valStr;
    }
    renderExceptions(settings.sites || {});
  } catch (err) {
    showError();
  }
}

async function onModeButtonClick(newMode) {
  if (!isHttpPage || !targetSiteHost) return;
  if (newMode === currentMode) return;

  hideError();
  try {
    const res = await ext.runtime.sendMessage({
      type: 'set-site',
      host: targetSiteHost,
      mode: newMode,
    });
    if (!res || !res.ok) {
      showError();
      return;
    }
    updateModeUI(newMode);
    reloadBtn.hidden = false;
    await loadSettings();
    await loadSiteStatus();
  } catch (err) {
    showError();
  }
}

reloadBtn.addEventListener('click', async () => {
  if (currentTabId == null) return;
  hideError();
  try {
    await ext.tabs.reload(currentTabId);
    reloadBtn.hidden = true;
  } catch (err) {
    showError();
  }
});

unloadSelect.addEventListener('change', async () => {
  hideError();
  const minutes = Number(unloadSelect.value);
  try {
    const res = await ext.runtime.sendMessage({
      type: 'set-unload-minutes',
      minutes,
    });
    if (!res || !res.ok) {
      showError();
    }
  } catch (err) {
    showError();
  }
});

exceptionsList.addEventListener('click', async (event) => {
  const btn = event.target.closest('.btn-remove');
  if (!btn) return;
  const host = btn.dataset.host;
  if (!host) return;

  hideError();
  try {
    const res = await ext.runtime.sendMessage({
      type: 'set-site',
      host,
      mode: 'normal',
    });
    if (!res || !res.ok) {
      showError();
      return;
    }
    await loadSettings();
    if (isHttpPage && currentTabHost) {
      const prevMode = currentMode;
      await loadSiteStatus();
      if (currentMode !== prevMode) {
        reloadBtn.hidden = false;
      }
    }
  } catch (err) {
    showError();
  }
});

modeButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    const mode = btn.dataset.mode;
    if (mode) onModeButtonClick(mode);
  });
});

async function init() {
  hideError();

  try {
    const tabs = await ext.tabs.query({ active: true, currentWindow: true });
    const tab = tabs && tabs[0];
    if (tab) {
      currentTabId = tab.id;
      let urlObj = null;
      try {
        if (tab.url) urlObj = new URL(tab.url);
      } catch (e) {
        urlObj = null;
      }

      if (urlObj && (urlObj.protocol === 'http:' || urlObj.protocol === 'https:')) {
        isHttpPage = true;
        currentTabHost = urlObj.hostname;
        targetSiteHost = urlObj.hostname;
        siteHostEl.textContent = currentTabHost;
        siteHostEl.title = currentTabHost;
        siteControlsEl.hidden = false;
        unsupportedEl.hidden = true;
      } else {
        isHttpPage = false;
        currentTabHost = null;
        targetSiteHost = null;
        siteControlsEl.hidden = true;
        unsupportedEl.hidden = false;
        if (urlObj) {
          siteHostEl.textContent = urlObj.hostname || (urlObj.protocol === 'about:' ? `about:${urlObj.pathname}` : urlObj.protocol);
          siteHostEl.title = tab.url || '';
        } else if (tab.title) {
          siteHostEl.textContent = tab.title;
          siteHostEl.title = tab.title;
        } else {
          siteHostEl.textContent = '';
        }
      }
    } else {
      isHttpPage = false;
      siteControlsEl.hidden = true;
      unsupportedEl.hidden = false;
    }

    if (isHttpPage) {
      await loadSiteStatus();
    }
    await loadSettings();
  } catch (err) {
    showError();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
