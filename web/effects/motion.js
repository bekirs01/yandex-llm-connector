const TOKEN = Symbol.for("yandex-llm-connector.motion");
const DEFAULT_MAX = 3;
const HARD_MAX = 5;
const UNCLAMPED_MAX = 16;
const EASE = 0.17;
const WINDOW_EASE = 0.14;
const WINDOW_MAX = 3.5;
const WINDOW_PERSPECTIVE = "1320px";
const SETTLE = 0.012;
const PROPS = [
  "--motion-perspective",
  "--motion-lift",
  "--motion-tilt-x",
  "--motion-tilt-y",
  "--motion-tilt-gx",
  "--motion-tilt-gy",
  "--motion-tilt-i",
  "--motion-shadow-x",
  "--motion-shadow-y",
];
const PROTECTED = 'textarea, [contenteditable="true"], [data-composer], [data-message-stream], [data-messages]';

let active = false;
let bindings = new Map();
let windowTilt = null;
let observer = null;
let queries = [];
let scheduled = 0;
let onScroll = null;
let onResize = null;
let onQuery = null;

function clamp01(value) {
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function declaredMax(node) {
  const raw = node.getAttribute("data-tilt-max");
  const cap = node.hasAttribute("data-tilt-unclamped") ? UNCLAMPED_MAX : HARD_MAX;
  if (raw == null || String(raw).trim() === "") return Math.min(DEFAULT_MAX, cap);
  const value = Number(raw);
  if (!Number.isFinite(value)) return Math.min(DEFAULT_MAX, cap);
  if (value < 0) return 0;
  if (value > cap) return cap;
  return value;
}

function maxForRect(node, rect) {
  const max = declaredMax(node);
  if (node.hasAttribute("data-tilt-unclamped")) return max;
  const viewportWide = rect.width > window.innerWidth - 32;
  const viewportTall = rect.height > window.innerHeight - 32;
  if (viewportWide || viewportTall || rect.width >= 720 || rect.height >= 420) {
    return Math.min(max, 1.8);
  }
  if (rect.width >= 480 || rect.height >= 280) {
    return Math.min(max, 2.6);
  }
  return max;
}

function interactiveAllowed() {
  return queries.every((query) => !query.matches);
}

function isProtected(node) {
  return node.matches(PROTECTED) || Boolean(node.closest(PROTECTED)) || Boolean(node.querySelector(PROTECTED));
}

function prepareAmbient() {
  const nodes = document.querySelectorAll("[data-ambient-background]");
  for (const node of nodes) {
    if (!node.hasAttribute("aria-hidden")) node.setAttribute("aria-hidden", "true");
  }
}

function bind(node) {
  let frame = 0;
  let hover = false;
  let rect = null;
  let enabled = interactiveAllowed();
  const visual = node.querySelector("[data-tilt-visual]");
  const unclamped = node.hasAttribute("data-tilt-unclamped") && visual;
  const target = { rx: 0, ry: 0, gx: 50, gy: 42, i: 0 };
  const current = { rx: 0, ry: 0, gx: 50, gy: 42, i: 0 };

  function clearProps() {
    node.classList.remove("motion-tilt-live");
    for (const prop of PROPS) node.style.removeProperty(prop);
  }

  function stop() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
  }

  function resetMotion() {
    stop();
    hover = false;
    rect = null;
    target.rx = 0;
    target.ry = 0;
    target.gx = 50;
    target.gy = 42;
    target.i = 0;
    current.rx = 0;
    current.ry = 0;
    current.gx = 50;
    current.gy = 42;
    current.i = 0;
    clearProps();
  }

  function measure() {
    rect = node.getBoundingClientRect();
  }

  function paint() {
    const neutral = !hover && Math.abs(current.rx) < 0.02 && Math.abs(current.ry) < 0.02 && current.i < 0.02;
    if (neutral || !visual) {
      current.rx = 0;
      current.ry = 0;
      current.i = 0;
      clearProps();
      return;
    }
    const peak = Math.max(declaredMax(node), 0.001);
    const lift = -4 * current.i;
    const shadowX = (-current.ry / peak) * 8;
    const shadowY = (current.rx / peak) * 5;
    node.classList.add("motion-tilt-live");
    node.style.setProperty("--motion-perspective", unclamped ? "840px" : "1100px");
    node.style.setProperty("--motion-lift", `${lift.toFixed(2)}px`);
    node.style.setProperty("--motion-tilt-x", `${current.rx.toFixed(3)}deg`);
    node.style.setProperty("--motion-tilt-y", `${current.ry.toFixed(3)}deg`);
    node.style.setProperty("--motion-tilt-gx", `${current.gx.toFixed(1)}%`);
    node.style.setProperty("--motion-tilt-gy", `${current.gy.toFixed(1)}%`);
    node.style.setProperty("--motion-tilt-i", current.i.toFixed(3));
    node.style.setProperty("--motion-shadow-x", `${shadowX.toFixed(2)}px`);
    node.style.setProperty("--motion-shadow-y", `${shadowY.toFixed(2)}px`);
  }

  function tick() {
    frame = 0;
    if (!enabled) {
      resetMotion();
      return;
    }
    current.rx += (target.rx - current.rx) * EASE;
    current.ry += (target.ry - current.ry) * EASE;
    current.gx += (target.gx - current.gx) * EASE;
    current.gy += (target.gy - current.gy) * EASE;
    current.i += (target.i - current.i) * EASE;
    paint();
    const settled =
      Math.abs(current.rx - target.rx) < SETTLE &&
      Math.abs(current.ry - target.ry) < SETTLE &&
      Math.abs(current.gx - target.gx) < 0.2 &&
      Math.abs(current.gy - target.gy) < 0.2 &&
      Math.abs(current.i - target.i) < SETTLE;
    if (!settled) frame = requestAnimationFrame(tick);
  }

  function start() {
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function onEnter() {
    if (!enabled || !visual) return;
    measure();
  }

  function onMove(event) {
    if (!enabled || !visual || event.pointerType !== "mouse") return;
    if (!rect || rect.width < 1 || rect.height < 1) measure();
    if (!rect || rect.width < 1 || rect.height < 1) return;
    hover = true;
    const x = clamp01((event.clientX - rect.left) / rect.width);
    const y = clamp01((event.clientY - rect.top) / rect.height);
    const max = maxForRect(node, rect);
    target.rx = (0.5 - y) * 2 * max;
    target.ry = (x - 0.5) * 2 * max;
    target.gx = 8 + x * 84;
    target.gy = 8 + y * 78;
    target.i = max === 0 ? 0 : 1;
    start();
  }

  function onLeave(event) {
    if (event.relatedTarget instanceof Node && node.contains(event.relatedTarget)) return;
    hover = false;
    rect = null;
    target.rx = 0;
    target.ry = 0;
    target.gx = 50;
    target.gy = 42;
    target.i = 0;
    if (enabled) start();
  }

  node.addEventListener("pointerenter", onEnter, { passive: true });
  node.addEventListener("pointermove", onMove, { passive: true });
  node.addEventListener("pointerleave", onLeave, { passive: true });
  node.addEventListener("pointercancel", onLeave, { passive: true });

  return {
    invalidate() {
      rect = null;
    },
    setEnabled(next) {
      enabled = next && Boolean(visual);
      if (!enabled) resetMotion();
    },
    release() {
      node.removeEventListener("pointerenter", onEnter);
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerleave", onLeave);
      node.removeEventListener("pointercancel", onLeave);
      resetMotion();
    },
  };
}

function bindWindow(node) {
  let frame = 0;
  let enabled = false;
  const stage = node.parentElement;
  const target = { rx: 0, ry: 0 };
  const current = { rx: 0, ry: 0 };

  function clearProps() {
    node.classList.remove("motion-window-live");
    node.style.removeProperty("--window-tilt-x");
    node.style.removeProperty("--window-tilt-y");
    if (stage) stage.style.removeProperty("perspective");
  }

  function stop() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
  }

  function resetMotion() {
    stop();
    target.rx = 0;
    target.ry = 0;
    current.rx = 0;
    current.ry = 0;
    clearProps();
  }

  function paint() {
    const resting =
      Math.abs(current.rx) < 0.02 &&
      Math.abs(current.ry) < 0.02 &&
      Math.abs(target.rx) < 0.02 &&
      Math.abs(target.ry) < 0.02;
    if (resting) {
      current.rx = 0;
      current.ry = 0;
      clearProps();
      return;
    }
    node.classList.add("motion-window-live");
    node.style.setProperty("--window-tilt-x", `${current.rx.toFixed(3)}deg`);
    node.style.setProperty("--window-tilt-y", `${current.ry.toFixed(3)}deg`);
    if (stage) stage.style.perspective = WINDOW_PERSPECTIVE;
  }

  function tick() {
    frame = 0;
    if (!enabled) {
      resetMotion();
      return;
    }
    current.rx += (target.rx - current.rx) * WINDOW_EASE;
    current.ry += (target.ry - current.ry) * WINDOW_EASE;
    paint();
    const settled =
      Math.abs(current.rx - target.rx) < SETTLE &&
      Math.abs(current.ry - target.ry) < SETTLE;
    if (!settled) frame = requestAnimationFrame(tick);
  }

  function start() {
    if (!enabled || frame) return;
    frame = requestAnimationFrame(tick);
  }

  function onMove(event) {
    if (!enabled || event.pointerType !== "mouse") return;
    const width = window.innerWidth;
    const height = window.innerHeight;
    if (width < 1 || height < 1) return;
    if (!document.hasFocus() || event.clientX < 0 || event.clientY < 0 || event.clientX > width || event.clientY > height) {
      neutralize();
      return;
    }
    const x = event.clientX / width;
    const y = event.clientY / height;
    target.rx = (0.5 - y) * 2 * WINDOW_MAX;
    target.ry = (x - 0.5) * 2 * WINDOW_MAX;
    start();
  }

  function neutralize() {
    target.rx = 0;
    target.ry = 0;
    if (enabled) start();
    else resetMotion();
  }

  function onLeave(event) {
    if (event.pointerType && event.pointerType !== "mouse") return;
    neutralize();
  }

  window.addEventListener("pointermove", onMove, { passive: true });
  document.documentElement.addEventListener("pointerleave", onLeave);
  window.addEventListener("blur", neutralize);

  return {
    node,
    setEnabled(next) {
      enabled = Boolean(next);
      if (!enabled) resetMotion();
    },
    release() {
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      window.removeEventListener("blur", neutralize);
      resetMotion();
    },
  };
}

function syncWindow() {
  if (!active) return;
  const node = document.querySelector("[data-window-tilt]");
  if (!node) {
    if (windowTilt) windowTilt.release();
    windowTilt = null;
    return;
  }
  if (!windowTilt || windowTilt.node !== node) {
    if (windowTilt) windowTilt.release();
    windowTilt = bindWindow(node);
  }
  windowTilt.setEnabled(interactiveAllowed());
}

function syncDom() {
  if (!active) return;
  prepareAmbient();
  const wanted = new Set();
  for (const node of document.querySelectorAll("[data-tilt]")) {
    if (!isProtected(node)) wanted.add(node);
  }
  for (const [node, binding] of bindings) {
    if (wanted.has(node)) continue;
    binding.release();
    bindings.delete(node);
  }
  const allowed = interactiveAllowed();
  for (const node of wanted) {
    if (bindings.has(node)) continue;
    const binding = bind(node);
    binding.setEnabled(allowed);
    bindings.set(node, binding);
  }
  syncWindow();
}

function requestSync() {
  if (!active || scheduled) return;
  scheduled = requestAnimationFrame(() => {
    scheduled = 0;
    syncDom();
  });
}

function syncMode() {
  const allowed = interactiveAllowed();
  for (const binding of bindings.values()) binding.setEnabled(allowed);
  if (windowTilt) windowTilt.setEnabled(allowed);
}

function teardown() {
  if (!active) return;
  active = false;
  if (scheduled) cancelAnimationFrame(scheduled);
  scheduled = 0;
  if (observer) observer.disconnect();
  observer = null;
  for (const query of queries) query.removeEventListener("change", onQuery);
  queries = [];
  if (onScroll) window.removeEventListener("scroll", onScroll, true);
  if (onResize) window.removeEventListener("resize", onResize);
  onScroll = null;
  onResize = null;
  onQuery = null;
  for (const binding of bindings.values()) binding.release();
  bindings = new Map();
  if (windowTilt) windowTilt.release();
  windowTilt = null;
  delete globalThis[TOKEN];
}

function init() {
  if (active || globalThis[TOKEN] || !document.body) return;
  active = true;
  globalThis[TOKEN] = true;
  bindings = new Map();
  onQuery = () => syncMode();
  queries = [
    window.matchMedia("(prefers-reduced-motion: reduce)"),
    window.matchMedia("(pointer: coarse)"),
    window.matchMedia("(hover: none)"),
    window.matchMedia("(max-width: 899px)"),
  ];
  for (const query of queries) query.addEventListener("change", onQuery);
  onScroll = () => {
    for (const binding of bindings.values()) binding.invalidate();
  };
  onResize = onScroll;
  window.addEventListener("scroll", onScroll, { passive: true, capture: true });
  window.addEventListener("resize", onResize, { passive: true });
  window.addEventListener("pagehide", teardown, { once: true });
  observer = new MutationObserver((mutations) => {
    if (!mutations.some((mutation) => mutation.type === "childList" || mutation.type === "attributes")) return;
    requestSync();
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["data-tilt"],
  });
  syncDom();
}

function boot() {
  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        try {
          init();
        } catch {
          teardown();
        }
      }, { once: true });
      return;
    }
    init();
  } catch {
    teardown();
  }
}

boot();

window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  try {
    init();
  } catch {
    teardown();
  }
});
