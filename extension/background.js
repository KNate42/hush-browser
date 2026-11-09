// Settings live in storage.local: { sites: { host: 'off' | 'strict' }, unloadMinutes: number }.
// Popup and unloader talk to this file only through runtime messages listed in onMessage.

const DEFAULTS = { sites: {}, unloadMinutes: 5 };

async function readSettings() {
  const stored = await browser.storage.local.get(DEFAULTS);
  return { sites: stored.sites, unloadMinutes: stored.unloadMinutes };
}

function hostPatterns(hosts) {
  return hosts.flatMap((host) => [`*://${host}/*`, `*://*.${host}/*`]);
}

function pageScript(id, file, matches, excludeMatches) {
  return {
    id,
    js: [file],
    matches,
    excludeMatches,
    runAt: 'document_start',
    allFrames: true,
    matchOriginAsFallback: true,
    world: 'MAIN',
    persistAcrossSessions: true,
  };
}

async function applySites(sites) {
  const hosts = Object.keys(sites);
  const special = hostPatterns(hosts);
  const strict = hostPatterns(hosts.filter((host) => sites[host] === 'strict'));

  const scripts = [pageScript('hush-normal', 'dist/normal.js', ['<all_urls>'], special)];
  if (strict.length) scripts.push(pageScript('hush-strict', 'dist/strict.js', strict, []));

  await browser.scripting.unregisterContentScripts().catch(() => {});
  await browser.scripting.registerContentScripts(scripts);
}

function siteMode(sites, host) {
  const parts = host.split('.');
  for (let index = 0; index < parts.length - 1; index += 1) {
    const candidate = parts.slice(index).join('.');
    if (sites[candidate]) return { mode: sites[candidate], host: candidate };
  }
  return { mode: 'normal', host };
}

async function setSite(host, mode) {
  const { sites } = await readSettings();
  delete sites[host];
  if (mode !== 'normal') sites[host] = mode;
  await browser.storage.local.set({ sites });
  await applySites(sites);
}

browser.runtime.onInstalled.addListener(async () => {
  const { sites } = await readSettings();
  await applySites(sites);
});

browser.runtime.onStartup.addListener(async () => {
  const registered = await browser.scripting.getRegisteredContentScripts();
  if (registered.length) return;
  const { sites } = await readSettings();
  await applySites(sites);
});

browser.runtime.onMessage.addListener((message) => {
  if (message.type === 'get-site') {
    return readSettings().then(({ sites }) => siteMode(sites, message.host));
  }
  if (message.type === 'set-site') {
    return setSite(message.host, message.mode).then(() => ({ ok: true }));
  }
  if (message.type === 'get-settings') return readSettings();
  if (message.type === 'set-unload-minutes') {
    return browser.storage.local.set({ unloadMinutes: message.minutes }).then(() => ({ ok: true }));
  }
  return undefined;
});
