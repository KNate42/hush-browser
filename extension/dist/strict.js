(() => {
const HUSH_LEVEL = "strict";
// Shared helpers for page-world modules. Build wraps this file and the modules into one IIFE.
const masked = new WeakMap();

function maskToString(view) {
  const proto = view.Function.prototype;
  const nativeToString = proto.toString;
  const replacement = {
    toString() {
      return nativeToString.call(masked.get(this) || this);
    },
  }.toString;
  masked.set(replacement, nativeToString);
  Object.defineProperty(proto, 'toString', {
    value: replacement,
    writable: true,
    configurable: true,
    enumerable: false,
  });
}

function dress(fake, original) {
  masked.set(fake, original);
  try {
    Object.defineProperty(fake, 'name', { value: original.name, configurable: true });
    Object.defineProperty(fake, 'length', { value: original.length, configurable: true });
  } catch (error) {}
  return fake;
}

function fakeGetter(proto, key, compute) {
  const descriptor = Object.getOwnPropertyDescriptor(proto, key);
  if (!descriptor || !descriptor.get) return;
  const originalGet = descriptor.get;
  const fake = {
    get [key]() {
      return compute(originalGet.call(this), this);
    },
  };
  const get = Object.getOwnPropertyDescriptor(fake, key).get;
  dress(get, originalGet);
  Object.defineProperty(proto, key, { ...descriptor, get });
}

function fakeMethod(proto, key, build) {
  const original = proto[key];
  if (typeof original !== 'function') return;
  const fake = {
    [key](...args) {
      return build(original, this, args);
    },
  }[key];
  dress(fake, original);
  Object.defineProperty(proto, key, {
    value: fake,
    writable: true,
    configurable: true,
    enumerable: Object.getOwnPropertyDescriptor(proto, key).enumerable,
  });
}

function silence(target, type, shouldStop) {
  target.addEventListener(
    type,
    (event) => {
      if (!shouldStop || shouldStop(event)) event.stopImmediatePropagation();
    },
    true,
  );
}

function isEditor(node) {
  let element = node && node.nodeType === 1 ? node : node && node.parentElement;
  if (!element) return false;
  if (element.isContentEditable) return true;
  // Code editors keep a hidden textarea and read the clipboard event from it.
  return Boolean(element.closest('.monaco-editor, .cm-editor, .CodeMirror, .ace_editor'));
}

function isPlainField(node) {
  if (!node || node.nodeType !== 1) return false;
  const tag = node.localName;
  return (tag === 'input' || tag === 'textarea') && !isEditor(node);
}

const modules = [];

function defineModule(name, levels, install) {
  modules.push({ name, levels, install });
}

function installAll(view, level) {
  for (const entry of modules) {
    if (!entry.levels.includes(level)) continue;
    // One broken module must not take the rest down.
    try {
      entry.install(view);
    } catch (error) {}
  }
}

defineModule('visibility', ['normal', 'strict'], (view) => {
  const documentProto = view.Document.prototype;
  fakeGetter(documentProto, 'hidden', () => false);
  fakeGetter(documentProto, 'visibilityState', () => 'visible');
  fakeMethod(documentProto, 'hasFocus', () => true);
  silence(view, 'visibilitychange');
  silence(view.document, 'visibilitychange');
});

defineModule('window-focus', ['normal', 'strict'], (view) => {
  const isWindowLevel = (event) => event.target === view || event.target === view.document;
  silence(view, 'blur', isWindowLevel);
  silence(view, 'focus', isWindowLevel);
});

defineModule('pointer-exit', ['normal', 'strict'], (view) => {
  const leftWindow = (event) =>
    !event.relatedTarget &&
    (event.target === view.document || event.target === view.document.documentElement);
  for (const type of ['mouseout', 'mouseleave', 'pointerout', 'pointerleave']) {
    silence(view, type, leftWindow);
    silence(view.document, type, leftWindow);
  }
});

defineModule('clipboard-events', ['normal'], (view) => {
  const notEditor = (event) => !isEditor(event.target);
  for (const type of ['paste', 'copy', 'cut']) silence(view, type, notEditor);
});

defineModule('clipboard-events-strict', ['strict'], (view) => {
  for (const type of ['paste', 'copy', 'cut']) silence(view, type);
});

defineModule('paste-input-type', ['normal', 'strict'], (view) => {
  const hiddenTypes = new Set(['insertFromPaste', 'insertFromDrop']);
  fakeGetter(view.InputEvent.prototype, 'inputType', (value, event) => {
    if (!hiddenTypes.has(value)) return value;
    return isPlainField(event.target) ? 'insertText' : value;
  });
});

defineModule('beacon', ['normal', 'strict'], (view) => {
  if (!view.Navigator.prototype.sendBeacon) return;
  fakeMethod(view.Navigator.prototype, 'sendBeacon', () => true);
});

defineModule('iframes', ['normal', 'strict'], (view) => {
  const proto = view.HTMLIFrameElement.prototype;
  const cover = (frameWindow) => {
    if (frameWindow) coverWindow(frameWindow);
    return frameWindow;
  };
  fakeGetter(proto, 'contentWindow', (value) => cover(value));
  fakeGetter(proto, 'contentDocument', (value) => {
    if (value) cover(value.defaultView);
    return value;
  });
});

defineModule('strict-activity', ['strict'], (view) => {
  const buttonUp = (event) => event.buttons === 0;
  for (const type of ['mousemove', 'pointermove']) silence(view, type, buttonUp);
  for (const type of ['scroll', 'scrollend', 'selectionchange', 'pagehide']) silence(view, type);
  silence(view.document, 'selectionchange');
});

defineModule('strict-performance', ['strict'], (view) => {
  fakeMethod(view.PerformanceObserver.prototype, 'observe', () => undefined);
});

const covered = new WeakSet();

function coverWindow(view) {
  try {
    if (covered.has(view)) return;
    covered.add(view);
    maskToString(view);
    installAll(view, HUSH_LEVEL);
  } catch (error) {
    // Cross-origin frames are not readable here; they get their own content script.
  }
}

coverWindow(window);

})();
