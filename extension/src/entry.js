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
