// Tracks user input to avoid discarding tabs with unsaved changes.

let dirty = false;

function isDirtyTarget(target) {
  if (!target) return false;
  const el = target.nodeType === 1 ? target : target.parentElement;
  if (!el) return false;

  const tag = el.tagName ? el.tagName.toLowerCase() : '';
  if (tag === 'input') {
    const type = (el.type || '').toLowerCase();
    return !['checkbox', 'radio', 'button', 'submit'].includes(type);
  }
  if (tag === 'textarea' || tag === 'select') return true;
  return Boolean(el.isContentEditable);
}

document.addEventListener(
  'input',
  (event) => {
    if (!event.isTrusted) return;
    const target = (event.composedPath && event.composedPath()[0]) || event.target;
    if (isDirtyTarget(target)) {
      dirty = true;
    }
  },
  true
);

// A real form submission loads a new document with a fresh script, so nothing resets the flag here.
browser.runtime.onMessage.addListener((message) => {
  if (message && message.type === 'is-dirty') {
    if (dirty) {
      return Promise.resolve({ dirty: true });
    }
  }
});
