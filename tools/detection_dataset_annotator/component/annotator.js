// Box editor for the detection dataset annotator (a Streamlit components v2 module, no build step).
//
// The screenshot is a plain <img>; every box is its own element above it, so the picture is never changed and
// "Save image as" gives the clean screenshot. All coordinates are source-image pixels; the stage is scaled with a
// CSS transform for zoom and pan.
//
// Streamlit calls the default export again whenever the data changes (after every autosave rerun) and runs only
// the last returned cleanup, on unmount. So one Annotator lives per mount point and later calls only update it:
// a rerun must never reset boxes that are still being edited.
//
// Python sends the sizes and timings (chip_px, editor_height, autosave_ms) with the data; the numbers below only
// shape the interaction itself.

const INSTANCES = new WeakMap();
const DESTROY_DELAY_MS = 100; // a cleanup followed by a new call for the same mount point is a re-render
const HANDLE_PX = 9; // resize handle reach on screen, at any zoom
const DRAG_START_PX = 3; // pointer travel on screen before a press becomes a drag
const HIT_PAD_PX = 2; // boxes are hit this far outside their border (screen pixels)
const MIN_BOX_PX = 2; // smaller drags are clicks, not new boxes (source pixels)
const HISTORY_LIMIT = 200;
const MAX_ZOOM = 16;
const MIN_ZOOM_OF_FIT = 0.5; // zoom out to half the fitted size at most
const WHEEL_ZOOM_RATE = 0.0015; // zoom factor exponent per wheel delta unit
const KEY_ZOOM_STEP = 1.25; // + / - zoom factor
const NEW_BOX_OFFSET = 8; // duplicate offset (source pixels)
const NUDGE_PX = 1; // arrows move / resize this much (source pixels)
const NUDGE_SHIFT_PX = 10; // ... with Shift
const SCALE_STEP_PX = 1; // , and . shrink / grow every side of a box this much (source pixels)
const SCALE_STEP_SHIFT_PX = 5; // ... with Shift
const SCALE_WHEEL_DELTA = 100; // wheel delta per resize step: one mouse-wheel notch; trackpads add up small deltas
const SCALE_UNDO_MS = 600; // resize steps closer together than this are one undo step (one wheel gesture)
const REVEAL_MARGIN_PX = 24; // Tab pans when the box comes closer than this to the viewport edge
const MANUAL = "manual"; // box source of drawn or changed boxes (constants.ANNOTATOR_MANUAL_SOURCE)

const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
const HANDLE_CURSORS = {
  nw: "nwse-resize",
  se: "nwse-resize",
  ne: "nesw-resize",
  sw: "nesw-resize",
  n: "ns-resize",
  s: "ns-resize",
  e: "ew-resize",
  w: "ew-resize",
};

const SHORTCUTS = [
  ["Drag on the screenshot", "draw a box with the current label"],
  ["Click / Shift+click", "select / add to selection (smallest box under the pointer)"],
  ["Alt+click", "cycle through boxes stacked under the pointer"],
  ["Drag box / handle", "move / resize"],
  ["1 … 9, 0", "label the selected boxes, or pick the label for new boxes"],
  ["/", "find a label by its name, icon name or other names (Enter: use the first one, Esc: clear)"],
  ["Del, Backspace", "delete selected"],
  ["Ctrl+D", "duplicate selected"],
  ["Ctrl+A", "select all"],
  ["Arrows (+Shift)", "move 1 px (10 px)"],
  ["Alt+Arrows (+Shift)", "resize 1 px (10 px)"],
  [", / . (+Shift)", "shrink / grow 1 px on every side (5 px), keeping the centre"],
  ["Tab / Shift+Tab", "next / previous box"],
  ["Ctrl+Z / Ctrl+Shift+Z, Ctrl+Y", "undo / redo"],
  ["Esc", "cancel drag, deselect, close help"],
  ["Wheel / + / -", "zoom; with boxes selected: grow / shrink them 1 px on every side"],
  ["Ctrl+wheel", "zoom, also with boxes selected"],
  ["Space+drag, middle drag", "pan"],
  ["F", "fit the screenshot"],
  ["C", "centre the screenshot (keeps the zoom)"],
  ["H / L", "hide boxes / show every label"],
  ["Enter", "mark reviewed and go to the next screenshot"],
  ["Shift+Enter", "toggle reviewed"],
  ["N or ] / P or [", "next / previous screenshot (edits are saved first)"],
  ["?", "this help"],
];

function el(tag, className, parent) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  parent?.appendChild(node);
  return node;
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function cloneBoxes(boxes) {
  return boxes.map((box) => ({ ...box }));
}

function isTyping(event) {
  const target = event.composedPath()[0];
  if (!(target instanceof Element)) return false;
  return target.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

class Annotator {
  constructor(root) {
    this.root = root;
    this.boxes = [];
    this.selected = new Set();
    this.hoverId = null;
    this.history = [];
    this.future = [];
    this.view = { zoom: 1, x: 0, y: 0 };
    this.fitZoom = null;
    this.fitted = false;
    this.drag = null;
    this.spaceDown = false;
    this.wheelSum = 0; // wheel delta not yet turned into box resize steps
    this.lastScale = { at: 0, selection: "" }; // the last resize step, to merge one gesture into one undo step
    this.active = true; // keys go to the editor until the user clicks elsewhere on the page
    this.showBoxes = true;
    this.showAllChips = false;
    this.seq = 0;
    this.sentSeq = 0;
    this.autosaveTimer = null;
    this.destroyTimer = null;
    this.newId = 0;
    this.session = Date.now().toString(36);
    this.currentLabel = null;
    this.data = null;
    this.labels = [];
    this.labelByName = {};
    this.labelFilter = ""; // words typed in the label finder
    this.colors = {};
    this.listeners = [];
    this.build();
    this.listen();
  }

  // ---- Streamlit glue -------------------------------------------------------------------------------------

  bind(component) {
    this.setStateValue = component.setStateValue;
    this.setTriggerValue = component.setTriggerValue;
    clearTimeout(this.destroyTimer);
    this.destroyTimer = null;
  }

  update(data) {
    const first = !this.data || this.data.image_key !== data.image_key || this.data.revision !== data.revision;
    this.data = data;
    this.labels = data.labels ?? [];
    this.labelByName = Object.fromEntries(this.labels.map((label) => [label.name, label]));
    this.colors = Object.fromEntries(this.labels.map((label) => [label.name, label.color]));
    if (!this.currentLabel || !this.colors[this.currentLabel]) {
      this.currentLabel = this.labels[0]?.name ?? "";
    }
    this.wrap.style.setProperty("--chip-px", `${data.chip_px}px`);
    this.wrap.style.height = `${data.editor_height}px`;
    if (first) {
      this.boxes = cloneBoxes(data.boxes ?? []);
      this.selected.clear();
      this.history = [];
      this.future = [];
      this.fitted = false;
      this.seq = 0;
      this.sentSeq = 0;
    }
    if (this.img.dataset.src !== data.image_url) {
      this.img.dataset.src = data.image_url ?? "";
      this.fitted = false;
      this.img.src = data.image_url ?? "";
    }
    this.stage.style.width = `${data.width}px`;
    this.stage.style.height = `${data.height}px`;
    if (!this.fitted) this.fit();
    this.renderAll();
  }

  scheduleDestroy() {
    clearTimeout(this.destroyTimer);
    this.destroyTimer = setTimeout(() => {
      this.destroyTimer = null;
      this.flushAutosave();
      this.destroy();
    }, DESTROY_DELAY_MS);
  }

  destroy() {
    for (const [target, type, handler, options] of this.listeners) {
      target.removeEventListener(type, handler, options);
    }
    this.listeners = [];
    this.resizeObserver?.disconnect();
    clearTimeout(this.autosaveTimer);
    this.wrap.remove();
    INSTANCES.delete(this.root);
  }

  payload() {
    return {
      image_key: this.data.image_key,
      revision: this.data.revision,
      seq: this.seq,
      boxes: this.boxes.map(({ id, label, x, y, w, h }) => ({
        id,
        label,
        x: round2(x),
        y: round2(y),
        w: round2(w),
        h: round2(h),
      })),
    };
  }

  changed() {
    this.seq += 1;
    clearTimeout(this.autosaveTimer);
    this.autosaveTimer = setTimeout(() => this.flushAutosave(), this.data.autosave_ms);
    this.renderStatus();
  }

  flushAutosave() {
    clearTimeout(this.autosaveTimer);
    this.autosaveTimer = null;
    if (!this.data || this.seq === this.sentSeq || !this.setStateValue) return;
    this.sentSeq = this.seq;
    this.setStateValue("edit", this.payload());
    this.renderStatus();
  }

  act(type) {
    // Navigation carries the latest boxes, so nothing typed since the last autosave is lost.
    clearTimeout(this.autosaveTimer);
    this.autosaveTimer = null;
    this.sentSeq = this.seq;
    this.statusEl.textContent = "Saving…";
    this.setTriggerValue("action", { type, ...this.payload() });
  }

  // ---- DOM ------------------------------------------------------------------------------------------------

  build() {
    this.wrap = el("div", "ann", this.root);
    const main = el("div", "ann-main", this.wrap);
    this.viewport = el("div", "ann-viewport", main);
    this.viewport.tabIndex = 0;
    this.stage = el("div", "ann-stage", this.viewport);
    this.img = el("img", "ann-shot", this.stage);
    this.img.alt = "screenshot";
    this.img.draggable = false;
    this.img.addEventListener("load", () => {
      if (!this.fitted) this.fit();
    });
    this.layer = el("div", "ann-boxes", this.stage);
    this.drawEl = el("div", "ann-draw", this.stage);
    this.drawEl.hidden = true;

    this.helpEl = el("div", "ann-help", this.viewport);
    this.helpEl.hidden = true;
    this.helpEl.setAttribute("role", "dialog");
    this.helpEl.setAttribute("aria-label", "Shortcuts");
    const card = el("div", "ann-help-card", this.helpEl);
    el("h3", "", card).textContent = "Shortcuts";
    const table = el("table", "", card);
    for (const [keys, what] of SHORTCUTS) {
      const row = el("tr", "", table);
      el("td", "ann-key", row).textContent = keys;
      el("td", "", row).textContent = what;
    }
    el("p", "ann-muted", card).textContent = "Edits save automatically. Press ? or Esc to close.";

    const side = el("div", "ann-side", main);
    const nav = el("div", "ann-row", side);
    this.prevBtn = this.button(nav, "◀ Prev", "Previous screenshot (P)", () => this.act("prev"));
    this.positionEl = el("span", "ann-position", nav);
    this.nextBtn = this.button(nav, "Next ▶", "Next screenshot (N)", () => this.act("next"));
    this.reviewBtn = this.button(side, "✓ Reviewed, next", "Mark reviewed and go to the next screenshot (Enter)", () =>
      this.act("review_next"),
    );
    this.reviewBtn.classList.add("ann-primary");
    this.reviewState = el("div", "ann-row ann-muted", side);
    this.statusEl = el("div", "ann-status", side);
    this.statusEl.setAttribute("aria-live", "polite");

    el("div", "ann-heading", side).textContent = "Labels";
    this.filterEl = el("input", "ann-filter", side);
    this.filterEl.type = "search";
    this.filterEl.placeholder = "Find a label (/)";
    this.filterEl.setAttribute("aria-label", "Find a label");
    this.filterEl.addEventListener("input", () => {
      this.labelFilter = this.filterEl.value.trim().toLowerCase();
      this.renderLegend();
    });
    this.filterEl.addEventListener("keydown", (event) => this.filterKey(event));
    this.legendEl = el("div", "ann-legend", side);

    el("div", "ann-heading", side).textContent = "Selection";
    this.inspectorEl = el("div", "ann-inspector", side);

    const view = el("div", "ann-row ann-tools", side);
    this.boxesBtn = this.button(view, "Boxes", "Hide or show boxes (H)", () => this.toggleBoxes());
    this.chipsBtn = this.button(view, "Labels", "Show every label (L)", () => this.toggleChips());
    this.button(view, "Fit", "Fit the screenshot (F)", () => this.fit());
    this.button(view, "Centre", "Centre the screenshot, keeping the zoom (C)", () => this.centre());
    this.helpBtn = this.button(view, "?", "Shortcuts (?)", () => this.toggleHelp());
    this.helpBtn.setAttribute("aria-label", "Shortcuts");
  }

  button(parent, text, title, onClick) {
    const node = el("button", "ann-btn", parent);
    node.type = "button";
    node.textContent = text;
    node.title = title;
    node.addEventListener("click", (event) => {
      event.preventDefault();
      onClick();
    });
    return node;
  }

  on(target, type, handler, options) {
    target.addEventListener(type, handler, options);
    this.listeners.push([target, type, handler, options]);
  }

  listen() {
    const viewport = this.viewport;
    this.on(viewport, "pointerdown", (event) => this.pointerDown(event));
    this.on(viewport, "pointermove", (event) => this.pointerMove(event));
    this.on(viewport, "pointerup", (event) => this.pointerUp(event));
    this.on(viewport, "pointercancel", () => this.cancelDrag());
    this.on(viewport, "pointerleave", () => {
      if (!this.drag) this.setHover(null);
    });
    this.on(viewport, "wheel", (event) => this.wheel(event), { passive: false });
    this.on(viewport, "auxclick", (event) => event.button === 1 && event.preventDefault());
    this.on(document, "keydown", (event) => this.keyDown(event), true);
    this.on(document, "keyup", (event) => {
      if (event.key === " ") this.spaceDown = false;
    });
    // Keys belong to the editor after a click inside it and stop after a click anywhere else on the page.
    this.on(document, "pointerdown", (event) => this.setActive(event.composedPath().includes(this.wrap)));
    this.resizeObserver = new ResizeObserver(() => {
      if (!this.fitted) this.fit();
    });
    this.resizeObserver.observe(viewport);
  }

  setActive(active) {
    this.active = active;
    this.wrap.classList.toggle("ann-inactive", !active);
  }

  // ---- geometry -------------------------------------------------------------------------------------------

  applyView() {
    const { zoom, x, y } = this.view;
    this.stage.style.transform = `translate(${x}px, ${y}px) scale(${zoom})`;
    this.stage.style.setProperty("--inv", String(1 / zoom));
  }

  fit() {
    if (!this.data) return;
    const width = this.viewport.clientWidth;
    const height = this.viewport.clientHeight;
    if (!width || !height || !this.data.width || !this.data.height) return;
    const zoom = Math.min(width / this.data.width, height / this.data.height);
    this.view = {
      zoom,
      x: (width - this.data.width * zoom) / 2,
      y: (height - this.data.height * zoom) / 2,
    };
    this.fitZoom = zoom;
    this.fitted = true;
    this.applyView();
  }

  centre() {
    // Put the screenshot back in the middle of the canvas at the current zoom (F also resets the zoom).
    if (!this.data) return;
    const { zoom } = this.view;
    this.view = {
      zoom,
      x: (this.viewport.clientWidth - this.data.width * zoom) / 2,
      y: (this.viewport.clientHeight - this.data.height * zoom) / 2,
    };
    this.applyView();
  }

  zoomAt(factor, clientX, clientY) {
    const rect = this.viewport.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const low = (this.fitZoom ?? this.view.zoom) * MIN_ZOOM_OF_FIT;
    const zoom = clamp(this.view.zoom * factor, low, MAX_ZOOM);
    const applied = zoom / this.view.zoom;
    this.view = { zoom, x: px - (px - this.view.x) * applied, y: py - (py - this.view.y) * applied };
    this.applyView();
  }

  zoomCentre(factor) {
    const rect = this.viewport.getBoundingClientRect();
    this.zoomAt(factor, rect.left + rect.width / 2, rect.top + rect.height / 2);
  }

  toImage(event) {
    const rect = this.viewport.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left - this.view.x) / this.view.zoom,
      y: (event.clientY - rect.top - this.view.y) / this.view.zoom,
    };
  }

  boxesAt(point) {
    // Every box under the point, smallest first (a map node inside a tower box wins).
    const pad = HIT_PAD_PX / this.view.zoom;
    return this.boxes
      .filter(
        (box) =>
          point.x >= box.x - pad &&
          point.x <= box.x + box.w + pad &&
          point.y >= box.y - pad &&
          point.y <= box.y + box.h + pad,
      )
      .sort((a, b) => a.w * a.h - b.w * b.h);
  }

  handleAt(point) {
    // Handles of the selected box (one selected) or the hovered one, so a small box can be resized directly.
    const candidates = [];
    if (this.selected.size === 1) candidates.push(this.selectedBoxes()[0]);
    if (this.hoverId) candidates.push(this.byId(this.hoverId));
    const reach = HANDLE_PX / this.view.zoom;
    for (const box of candidates) {
      if (!box) continue;
      for (const handle of HANDLES) {
        const spot = this.handlePoint(box, handle);
        if (Math.abs(point.x - spot.x) <= reach && Math.abs(point.y - spot.y) <= reach) return { box, handle };
      }
    }
    return null;
  }

  handlePoint(box, handle) {
    const x = handle.includes("w") ? box.x : handle.includes("e") ? box.x + box.w : box.x + box.w / 2;
    const y = handle.includes("n") ? box.y : handle.includes("s") ? box.y + box.h : box.y + box.h / 2;
    return { x, y };
  }

  byId(id) {
    return this.boxes.find((box) => box.id === id);
  }

  selectedBoxes() {
    return [...this.selected].map((id) => this.byId(id)).filter(Boolean);
  }

  clampBox(box) {
    const { width, height } = this.data;
    box.w = clamp(box.w, 1, width);
    box.h = clamp(box.h, 1, height);
    box.x = clamp(box.x, 0, width - box.w);
    box.y = clamp(box.y, 0, height - box.h);
  }

  makeId() {
    // Unique across mounts, so a box drawn after coming back never shares an id with one drawn before.
    this.newId += 1;
    return `new-${this.session}-${this.newId}`;
  }

  markEdited(box) {
    box.source = MANUAL;
    box.score = null;
  }

  // ---- history --------------------------------------------------------------------------------------------

  snapshot() {
    this.history.push(cloneBoxes(this.boxes));
    if (this.history.length > HISTORY_LIMIT) this.history.shift();
    this.future = [];
  }

  undo() {
    if (!this.history.length) return;
    this.future.push(cloneBoxes(this.boxes));
    this.boxes = this.history.pop();
    this.afterRestore();
  }

  redo() {
    if (!this.future.length) return;
    this.history.push(cloneBoxes(this.boxes));
    this.boxes = this.future.pop();
    this.afterRestore();
  }

  afterRestore() {
    for (const id of [...this.selected]) if (!this.byId(id)) this.selected.delete(id);
    this.changed();
    this.renderAll();
  }

  // ---- pointer --------------------------------------------------------------------------------------------

  pointerDown(event) {
    this.setActive(true);
    this.viewport.focus({ preventScroll: true });
    if (event.button === 2) return; // keep the browser's menu (Save image as gives the clean screenshot)
    event.preventDefault();
    const point = this.toImage(event);
    if (event.button === 1 || this.spaceDown) {
      this.drag = { kind: "pan", startX: event.clientX, startY: event.clientY, view: { ...this.view } };
    } else if (!this.showBoxes) {
      return;
    } else {
      this.drag = this.startBoxDrag(event, point);
    }
    this.viewport.setPointerCapture(event.pointerId);
    this.drag.moved = false;
    this.renderAll();
  }

  startBoxDrag(event, point) {
    // A press on a handle resizes, on a box selects and moves, elsewhere draws a new box.
    const handle = this.handleAt(point);
    if (handle) {
      this.select(handle.box.id);
      return { kind: "resize", handle: handle.handle, start: point, box: { ...handle.box }, id: handle.box.id };
    }
    const under = this.boxesAt(point);
    if (!under.length) {
      if (!event.shiftKey) this.selected.clear();
      return { kind: "draw", start: point };
    }
    let target = under[0];
    if (event.altKey && under.length > 1) {
      const current = under.findIndex((box) => this.selected.has(box.id));
      target = under[(current + 1) % under.length];
    }
    if (event.shiftKey) {
      if (this.selected.has(target.id)) this.selected.delete(target.id);
      else this.selected.add(target.id);
    } else if (!this.selected.has(target.id) || event.altKey) {
      this.select(target.id);
    }
    return { kind: "move", start: point, originals: cloneBoxes(this.selectedBoxes()) };
  }

  pointerMove(event) {
    const point = this.toImage(event);
    const drag = this.drag;
    if (!drag) {
      this.hoverAt(point);
      return;
    }
    if (drag.kind === "pan") {
      this.view = {
        ...drag.view,
        x: drag.view.x + event.clientX - drag.startX,
        y: drag.view.y + event.clientY - drag.startY,
      };
      this.applyView();
      return;
    }
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    if (!drag.moved && Math.hypot(dx, dy) * this.view.zoom < DRAG_START_PX) return;
    if (!drag.moved && drag.kind !== "draw") this.snapshot();
    drag.moved = true;
    if (drag.kind === "move") this.dragMove(drag, dx, dy);
    else if (drag.kind === "resize") this.dragResize(drag, dx, dy);
    else if (drag.kind === "draw") this.dragDraw(drag, point);
  }

  hoverAt(point) {
    if (!this.showBoxes) return;
    const handle = this.handleAt(point);
    const under = this.boxesAt(point);
    this.setHover(handle?.box.id ?? under[0]?.id ?? null);
    let cursor = "crosshair";
    if (this.spaceDown) cursor = "grab";
    else if (handle) cursor = HANDLE_CURSORS[handle.handle];
    else if (under.length) cursor = "move";
    this.viewport.style.cursor = cursor;
  }

  dragMove(drag, dx, dy) {
    for (const original of drag.originals) {
      const box = this.byId(original.id);
      if (!box) continue;
      box.x = original.x + dx;
      box.y = original.y + dy;
      this.clampBox(box);
      this.markEdited(box);
      this.updateBoxNode(box);
    }
  }

  dragResize(drag, dx, dy) {
    const box = this.byId(drag.id);
    if (!box) return;
    const { width, height } = this.data;
    const start = drag.box;
    const left = clamp(start.x + (drag.handle.includes("w") ? dx : 0), 0, width);
    const right = clamp(start.x + start.w + (drag.handle.includes("e") ? dx : 0), 0, width);
    const top = clamp(start.y + (drag.handle.includes("n") ? dy : 0), 0, height);
    const bottom = clamp(start.y + start.h + (drag.handle.includes("s") ? dy : 0), 0, height);
    box.x = Math.min(left, right);
    box.y = Math.min(top, bottom);
    box.w = Math.max(1, Math.abs(right - left));
    box.h = Math.max(1, Math.abs(bottom - top));
    this.markEdited(box);
    this.updateBoxNode(box);
  }

  dragDraw(drag, point) {
    const { width, height } = this.data;
    const left = clamp(Math.min(drag.start.x, point.x), 0, width);
    const top = clamp(Math.min(drag.start.y, point.y), 0, height);
    const right = clamp(Math.max(drag.start.x, point.x), 0, width);
    const bottom = clamp(Math.max(drag.start.y, point.y), 0, height);
    drag.rect = { x: left, y: top, w: right - left, h: bottom - top };
    Object.assign(this.drawEl.style, {
      left: `${left}px`,
      top: `${top}px`,
      width: `${right - left}px`,
      height: `${bottom - top}px`,
      borderColor: this.colors[this.currentLabel] ?? "#fff",
    });
    this.drawEl.hidden = false;
  }

  pointerUp(event) {
    const drag = this.drag;
    this.drag = null;
    if (this.viewport.hasPointerCapture(event.pointerId)) this.viewport.releasePointerCapture(event.pointerId);
    this.drawEl.hidden = true;
    if (!drag) return;
    if (drag.moved && drag.kind === "draw" && drag.rect?.w >= MIN_BOX_PX && drag.rect?.h >= MIN_BOX_PX) {
      this.snapshot();
      const box = { id: this.makeId(), label: this.currentLabel, ...drag.rect, score: null, source: MANUAL };
      this.boxes.push(box);
      this.select(box.id);
      this.changed();
    } else if (drag.moved && (drag.kind === "move" || drag.kind === "resize")) {
      this.changed();
    }
    this.renderAll();
  }

  cancelDrag() {
    const drag = this.drag;
    if (!drag) return;
    this.drag = null;
    this.drawEl.hidden = true;
    if ((drag.kind === "move" || drag.kind === "resize") && drag.moved) {
      this.boxes = this.history.pop() ?? this.boxes;
    }
    this.renderAll();
  }

  wheel(event) {
    event.preventDefault();
    if (this.selected.size && !(event.ctrlKey || event.metaKey)) {
      // A selected box is resized from its centre; Shift+wheel scrolls sideways in some browsers, so read both.
      this.wheelSum += event.deltaY || event.deltaX;
      const steps = Math.trunc(this.wheelSum / SCALE_WHEEL_DELTA);
      if (steps) {
        this.wheelSum -= steps * SCALE_WHEEL_DELTA;
        this.scaleSelected(-steps * (event.shiftKey ? SCALE_STEP_SHIFT_PX : SCALE_STEP_PX));
      }
      return;
    }
    this.zoomAt(Math.exp(-event.deltaY * WHEEL_ZOOM_RATE), event.clientX, event.clientY);
  }

  // ---- keyboard -------------------------------------------------------------------------------------------

  keyDown(event) {
    if (!this.active || !this.data || isTyping(event)) return;
    const handled = event.ctrlKey || event.metaKey ? this.commandKey(event) : this.plainKey(event);
    if (handled) {
      event.preventDefault();
      event.stopPropagation(); // Streamlit's own page shortcuts must not also fire
    }
  }

  commandKey(event) {
    // Ctrl / Cmd shortcuts; anything else (copy, paste, reload …) is left to the browser.
    switch (event.key.toLowerCase()) {
      case "z":
        if (event.shiftKey) this.redo();
        else this.undo();
        return true;
      case "y":
        this.redo();
        return true;
      case "d":
        this.duplicate();
        return true;
      case "a":
        this.selected = new Set(this.boxes.map((box) => box.id));
        this.renderAll();
        return true;
      default:
        return false;
    }
  }

  plainKey(event) {
    const { key, shiftKey } = event;
    if (key.startsWith("Arrow")) {
      this.nudge(key, shiftKey ? NUDGE_SHIFT_PX : NUDGE_PX, event.altKey);
      return true;
    }
    switch (key.length === 1 ? key.toLowerCase() : key) {
      case " ":
        this.spaceDown = true;
        this.viewport.style.cursor = "grab";
        return true;
      case "Escape":
        this.escape();
        return true;
      case "Delete":
      case "Backspace":
        this.deleteSelected();
        return true;
      case "Tab":
        this.cycle(shiftKey ? -1 : 1);
        return true;
      case "Enter":
        this.act(shiftKey ? "toggle_review" : "review_next");
        return true;
      case "n":
      case "]":
        this.act("next");
        return true;
      case "p":
      case "[":
        this.act("prev");
        return true;
      case "h":
        this.toggleBoxes();
        return true;
      case "l":
        this.toggleChips();
        return true;
      case "f":
        this.fit();
        return true;
      case "c":
        this.centre();
        return true;
      case ",":
      case "<":
        this.scaleSelected(-(shiftKey ? SCALE_STEP_SHIFT_PX : SCALE_STEP_PX));
        return true;
      case ".":
      case ">":
        this.scaleSelected(shiftKey ? SCALE_STEP_SHIFT_PX : SCALE_STEP_PX);
        return true;
      case "+":
      case "=":
        if (this.selected.size) this.scaleSelected(SCALE_STEP_PX);
        else this.zoomCentre(KEY_ZOOM_STEP);
        return true;
      case "-":
      case "_":
        if (this.selected.size) this.scaleSelected(-SCALE_STEP_PX);
        else this.zoomCentre(1 / KEY_ZOOM_STEP);
        return true;
      case "?":
        this.toggleHelp();
        return true;
      case "/":
        this.filterEl.focus();
        this.filterEl.select();
        return true;
      default: {
        const label = this.labels.find((item) => item.hotkey && item.hotkey === key);
        if (label) this.useLabel(label.name);
        return Boolean(label);
      }
    }
  }

  filterKey(event) {
    // In the label finder: Enter uses the first label it shows and gives the keys back to the editor; Esc clears it.
    if (event.key === "Enter") {
      const [first] = this.filteredLabels();
      if (first) this.useLabel(first.name);
      this.viewport.focus();
    } else if (event.key === "Escape") {
      this.filterEl.value = "";
      this.labelFilter = "";
      this.renderLegend();
      this.viewport.focus();
    } else {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
  }

  filteredLabels() {
    // Every typed word must appear in the label's name, its icon's poe2db name or its other names (label.search).
    const words = this.labelFilter.split(/\s+/).filter(Boolean);
    return this.labels.filter((label) => {
      const text = label.search || label.name.toLowerCase();
      return words.every((word) => text.includes(word));
    });
  }

  escape() {
    if (this.drag) this.cancelDrag();
    else if (!this.helpEl.hidden) this.toggleHelp();
    else {
      this.selected.clear();
      this.renderAll();
    }
  }

  // ---- edits ----------------------------------------------------------------------------------------------

  select(id) {
    this.selected.clear();
    if (id) this.selected.add(id);
  }

  useLabel(name) {
    const boxes = this.selectedBoxes();
    if (!boxes.length) {
      this.currentLabel = name;
      this.renderSide();
      return;
    }
    if (boxes.every((box) => box.label === name)) return;
    this.snapshot();
    for (const box of boxes) {
      box.label = name;
      this.markEdited(box);
    }
    this.currentLabel = name;
    this.changed();
    this.renderAll();
  }

  deleteSelected() {
    if (!this.selected.size) return;
    this.snapshot();
    this.boxes = this.boxes.filter((box) => !this.selected.has(box.id));
    this.selected.clear();
    this.changed();
    this.renderAll();
  }

  duplicate() {
    const boxes = this.selectedBoxes();
    if (!boxes.length) return;
    this.snapshot();
    this.selected.clear();
    for (const box of boxes) {
      const copy = {
        ...box,
        id: this.makeId(),
        x: box.x + NEW_BOX_OFFSET,
        y: box.y + NEW_BOX_OFFSET,
        score: null,
        source: MANUAL,
      };
      this.clampBox(copy);
      this.boxes.push(copy);
      this.selected.add(copy.id);
    }
    this.changed();
    this.renderAll();
  }

  editSelected(edit, { snapshot = true } = {}) {
    // Apply one edit to every selected box as one undo step.
    const boxes = this.selectedBoxes();
    if (!boxes.length) return;
    if (snapshot) this.snapshot();
    for (const box of boxes) {
      edit(box);
      this.clampBox(box);
      this.markEdited(box);
    }
    this.changed();
    this.renderAll();
  }

  nudge(key, step, resize) {
    const dx = key === "ArrowLeft" ? -step : key === "ArrowRight" ? step : 0;
    const dy = key === "ArrowUp" ? -step : key === "ArrowDown" ? step : 0;
    this.editSelected((box) => {
      if (resize) {
        box.w += dx;
        box.h += dy;
      } else {
        box.x += dx;
        box.y += dy;
      }
    });
  }

  scaleSelected(step) {
    // Grow (step > 0) or shrink every side of the selected boxes by step source px, so each keeps its centre:
    // the classical map-node boxes are fixed squares, often a little large for the map node.
    if (!this.selected.size) return;
    const now = Date.now();
    const selection = [...this.selected].sort().join(" ");
    const newGesture = now - this.lastScale.at > SCALE_UNDO_MS || this.lastScale.selection !== selection;
    this.lastScale = { at: now, selection };
    const resize = (box) => {
      const cx = box.x + box.w / 2;
      const cy = box.y + box.h / 2;
      box.w = Math.max(MIN_BOX_PX, box.w + 2 * step);
      box.h = Math.max(MIN_BOX_PX, box.h + 2 * step);
      box.x = cx - box.w / 2;
      box.y = cy - box.h / 2;
    };
    this.editSelected(resize, { snapshot: newGesture }); // one wheel gesture is one undo step
  }

  cycle(step) {
    if (!this.boxes.length) return;
    const order = [...this.boxes].sort((a, b) => a.y - b.y || a.x - b.x);
    const current = order.findIndex((box) => this.selected.has(box.id));
    const index = current < 0 ? (step > 0 ? 0 : order.length - 1) : (current + step + order.length) % order.length;
    const box = order[index];
    this.select(box.id);
    this.reveal(box);
    this.renderAll();
  }

  reveal(box) {
    // Pan so the box is on screen (centred if it was off screen), keeping the zoom.
    const { zoom, x, y } = this.view;
    const width = this.viewport.clientWidth;
    const height = this.viewport.clientHeight;
    const left = box.x * zoom + x;
    const top = box.y * zoom + y;
    const margin = REVEAL_MARGIN_PX;
    if (left < margin || top < margin || left + box.w * zoom > width - margin || top + box.h * zoom > height - margin) {
      this.view = {
        zoom,
        x: width / 2 - (box.x + box.w / 2) * zoom,
        y: height / 2 - (box.y + box.h / 2) * zoom,
      };
      this.applyView();
    }
  }

  toggleBoxes() {
    this.showBoxes = !this.showBoxes;
    if (!this.showBoxes) this.selected.clear();
    this.renderAll();
  }

  toggleChips() {
    this.showAllChips = !this.showAllChips;
    this.renderAll();
  }

  toggleHelp() {
    this.helpEl.hidden = !this.helpEl.hidden;
    this.helpBtn.setAttribute("aria-pressed", String(!this.helpEl.hidden));
  }

  boxNode(id) {
    return id ? this.layer.querySelector(`[data-id="${CSS.escape(id)}"]`) : null;
  }

  setHover(id) {
    if (this.hoverId === id) return;
    this.boxNode(this.hoverId)?.classList.remove("hover");
    this.hoverId = id;
    this.boxNode(id)?.classList.add("hover");
  }

  // ---- rendering ------------------------------------------------------------------------------------------

  renderAll() {
    this.applyView();
    this.renderBoxes();
    this.renderSide();
  }

  renderBoxes() {
    this.layer.replaceChildren();
    this.layer.hidden = !this.showBoxes;
    this.wrap.classList.toggle("ann-all-chips", this.showAllChips);
    // Larger boxes first, so smaller ones (map nodes inside a tower box) are drawn on top.
    const order = [...this.boxes].sort((a, b) => b.w * b.h - a.w * a.h);
    for (const box of order) {
      const node = el("div", "ann-box", this.layer);
      node.dataset.id = box.id;
      node.style.setProperty("--c", this.colors[box.label] ?? "#ffffff");
      node.classList.toggle("selected", this.selected.has(box.id));
      node.classList.toggle("hover", box.id === this.hoverId);
      const chip = el("span", "ann-chip", node);
      if (this.labelByName[box.label]?.picture) this.picture(chip, this.labelByName[box.label], "ann-chip-pic");
      chip.append(box.label);
      for (const handle of HANDLES) el("span", `ann-handle ${handle}`, node);
      this.updateBoxNode(box, node);
    }
  }

  updateBoxNode(box, node = this.boxNode(box.id)) {
    // Geometry and source style of one box element (during a drag only the dragged boxes are updated).
    if (!node) return;
    Object.assign(node.style, { left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px` });
    node.classList.toggle("manual", box.source === MANUAL);
  }

  renderSide() {
    const data = this.data;
    if (!data) return;
    this.positionEl.textContent = data.position ?? "";
    this.prevBtn.disabled = !data.has_prev;
    this.nextBtn.disabled = !data.has_next;
    this.reviewState.textContent = data.reviewed ? "✓ Reviewed" : "Not reviewed yet";
    this.reviewState.classList.toggle("ann-ok", Boolean(data.reviewed));
    this.boxesBtn.setAttribute("aria-pressed", String(this.showBoxes));
    this.chipsBtn.setAttribute("aria-pressed", String(this.showAllChips));
    this.renderStatus();
    this.renderLegend();
    this.renderInspector();
  }

  picture(parent, label, className) {
    // The label's picture (an icon's art), or an empty slot of the same size so the names line up.
    if (!label?.picture) return el("span", className, parent);
    const img = el("img", className, parent);
    img.src = label.picture;
    img.alt = "";
    img.draggable = false;
    return img;
  }

  labelText(parent, name, label) {
    // The label's name, with its icon's poe2db name under it.
    const text = el("span", "ann-text", parent);
    el("span", "ann-name", text).textContent = name;
    if (label?.title) el("span", "ann-title", text).textContent = label.title;
    return text;
  }

  renderLegend() {
    const counts = {};
    for (const box of this.boxes) counts[box.label] = (counts[box.label] ?? 0) + 1;
    this.legendEl.replaceChildren();
    const shown = this.filteredLabels();
    for (const label of shown) {
      const row = el("button", "ann-label", this.legendEl);
      row.type = "button";
      const what = label.title ? `${label.name} (${label.title})` : label.name;
      row.title = this.selected.size ? `Label the selected boxes ${what}` : `Draw ${what} boxes`;
      row.setAttribute("aria-pressed", String(label.name === this.currentLabel));
      el("span", "ann-key", row).textContent = label.hotkey || "·";
      el("span", "ann-swatch", row).style.background = label.color;
      this.picture(row, label, "ann-pic");
      this.labelText(row, label.name, label);
      el("span", "ann-count", row).textContent = String(counts[label.name] ?? 0);
      row.addEventListener("click", () => this.useLabel(label.name));
    }
    if (!shown.length) el("p", "ann-muted", this.legendEl).textContent = "No label matches.";
  }

  renderStatus() {
    if (!this.data) return;
    const saved = (this.data.saved_seq ?? 0) >= this.seq;
    const waiting = this.seq !== this.sentSeq;
    const state = saved ? "saved" : waiting ? "editing…" : "saving…";
    this.statusEl.textContent = `${this.boxes.length} boxes · ${state}`;
    this.statusEl.classList.toggle("ann-ok", saved);
  }

  renderInspector() {
    const panel = this.inspectorEl;
    panel.replaceChildren();
    const boxes = this.selectedBoxes();
    if (!boxes.length) {
      el("p", "ann-muted", panel).textContent =
        `Click a box, or drag on the screenshot to draw a ${this.currentLabel} box.`;
      return;
    }
    if (boxes.length > 1) {
      el("p", "", panel).textContent = `${boxes.length} boxes selected. Press a number to label them.`;
      this.button(panel, "Delete", "Delete selected (Del)", () => this.deleteSelected());
      return;
    }
    const [box] = boxes;
    const current = el("div", "ann-row ann-current", panel);
    this.picture(current, this.labelByName[box.label], "ann-pic-large");
    this.labelText(current, box.label, this.labelByName[box.label]);
    const select = el("select", "ann-select", panel);
    select.setAttribute("aria-label", "Label");
    for (const label of this.labels) {
      const option = el("option", "", select);
      option.value = label.name;
      const name = label.title ? `${label.name} — ${label.title}` : label.name;
      option.textContent = label.hotkey ? `${label.hotkey}  ${name}` : name;
    }
    if (!this.colors[box.label]) {
      const option = el("option", "", select);
      option.value = option.textContent = box.label;
    }
    select.value = box.label;
    select.addEventListener("change", () => this.useLabel(select.value));
    const grid = el("div", "ann-grid", panel);
    for (const field of ["x", "y", "w", "h"]) {
      const label = el("label", "", grid);
      el("span", "", label).textContent = field.toUpperCase();
      const input = el("input", "", label);
      input.type = "number";
      input.step = "1";
      input.value = String(round2(box[field]));
      input.addEventListener("change", () => {
        const value = Number(input.value);
        if (!Number.isFinite(value)) return;
        this.snapshot();
        box[field] = value;
        this.clampBox(box);
        this.markEdited(box);
        this.changed();
        this.renderAll();
      });
    }
    const score = box.score == null ? "" : ` · score ${Number(box.score).toFixed(3)}`;
    el("p", "ann-muted", panel).textContent = `${box.source || MANUAL}${score}`;
    this.button(panel, "Delete", "Delete selected (Del)", () => this.deleteSelected());
  }
}

export default function (component) {
  const { parentElement, data } = component;
  let editor = INSTANCES.get(parentElement);
  if (!editor) {
    editor = new Annotator(parentElement);
    INSTANCES.set(parentElement, editor);
  }
  editor.bind(component);
  editor.update(data);
  return () => editor.scheduleDestroy();
}
