// Unloads inactive tabs that have no unsaved user changes.

browser.alarms.create('hush-unload', { periodInMinutes: 1 });

function isUnloadable(tab, cutoff) {
  if (!tab.id || tab.active || tab.pinned || tab.audible || tab.discarded) return false;
  if (tab.status === 'loading') return false;
  const sharing = tab.sharingState;
  if (sharing && (sharing.camera || sharing.microphone || sharing.screen)) return false;
  if (!tab.url || (!tab.url.startsWith('http:') && !tab.url.startsWith('https:'))) return false;
  return Boolean(tab.lastAccessed) && tab.lastAccessed < cutoff;
}

browser.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm && alarm.name !== 'hush-unload') return;

  try {
    const { unloadMinutes } = await readSettings();
    if (!unloadMinutes || unloadMinutes <= 0) return;

    const cutoff = Date.now() - unloadMinutes * 60 * 1000;
    const tabs = await browser.tabs.query({});

    for (const tab of tabs) {
      if (!isUnloadable(tab, cutoff)) continue;

      try {
        const response = await browser.tabs.sendMessage(tab.id, { type: 'is-dirty' });
        if (response && response.dirty) continue;

        // The answer above is asynchronous, so the tab may have been used in the meantime.
        const current = await browser.tabs.get(tab.id);
        if (!isUnloadable(current, cutoff)) continue;

        await browser.tabs.discard(tab.id);
      } catch {
        // A tab without a content script or one that has just closed stays as it is.
      }
    }
  } catch {
    // Ignore top-level alarm error
  }
});
