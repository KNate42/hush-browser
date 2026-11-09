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
