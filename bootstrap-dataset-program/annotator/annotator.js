// Box editor for the RF-DETR dataset bootstrapper (a Streamlit components v2 module, no build step).
//
// The screenshot is a plain <img>; every box is its own element above it, so the picture is never changed and
// "Save image as" gives the clean screenshot. All coordinates are source-image pixels; the stage is scaled with a
// CSS transform for zoom and pan.
//
// Streamlit calls the default export again whenever the data changes (after every autosave rerun) and runs only
// the last returned cleanup, on unmount. So one Annotator lives per mount point and later calls only update it:
// a rerun must never reset boxes that are still being edited.

const INSTANCES = new WeakMap();
const DESTROY_DELAY_MS = 100; // a cleanup followed by a new call for the same mount point is a re-render
const HANDLE_PX = 9; // resize handle size on screen, at any zoom
const MIN_BOX_PX = 2; // smaller drags are clicks, not new boxes (source pixels)
const HISTORY_LIMIT = 200;
const MAX_ZOOM = 16;
const NEW_BOX_OFFSET = 8; // duplicate offset (source pixels)
const SCALE_STEP_PX = 1; // , and . shrink / grow every side of a box this much (source pixels)
const SCALE_STEP_SHIFT_PX = 5; // ... with Shift
const SCALE_WHEEL_DELTA = 100; // wheel delta per resize step: one mouse-wheel notch; trackpads add up small deltas
const SCALE_UNDO_MS = 600; // resize steps closer together than this are one undo step (one wheel gesture)

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
  if (parent) parent.appendChild(node);
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
    this.build();
    this.listen();
  }

  // ---- Streamlit glue -------------------------------------------------------------------------------------

  bind(component) {
    this.setStateValue = component.setStateValue;
    this.setTriggerValue = component.setTriggerValue;
    if (this.destroyTimer) {
      clearTimeout(this.destroyTimer);
      this.destroyTimer = null;
    }
  }

  update(data) {
    const first =
      !this.data || this.data.image_key !== data.image_key || this.data.revision !== data.revision;
    this.data = data;
    this.labels = data.labels || [];
    this.colors = Object.fromEntries(this.labels.map((label) => [label.name, label.color]));
    if (!this.currentLabel || !this.colors[this.currentLabel]) {
      this.currentLabel = this.labels.length ? this.labels[0].name : "";
    }
    this.wrap.style.setProperty("--chip-px", `${data.chip_px || 11}px`);
    this.wrap.style.height = `${data.editor_height || 760}px`;
    if (first) {
      this.boxes = cloneBoxes(data.boxes || []);
      this.selected.clear();
      this.history = [];
      this.future = [];
      this.fitted = false;
      this.seq = 0;
      this.sentSeq = 0;
    }
    if (this.img.dataset.src !== data.image_url) {
      this.img.dataset.src = data.image_url || "";
      this.fitted = false;
      this.img.src = data.image_url || "";
    }
    this.stage.style.width = `${data.width}px`;
    this.stage.style.height = `${data.height}px`;
    if (!this.fitted) this.fit();
    this.renderAll();
  }

  scheduleDestroy() {
    if (this.destroyTimer) clearTimeout(this.destroyTimer);
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
    if (this.resizeObserver) this.resizeObserver.disconnect();
    clearTimeout(this.autosaveTimer);
    this.wrap.remove();
    INSTANCES.delete(this.root);
  }

  payload() {
    return {
      image_key: this.data.image_key,
      revision: this.data.revision,
      seq: this.seq,
      boxes: this.boxes.map((box) => ({
        id: box.id,
        label: box.label,
        x: round2(box.x),
        y: round2(box.y),
        w: round2(box.w),
        h: round2(box.h),
      })),
    };
  }

  changed() {
    this.seq += 1;
    clearTimeout(this.autosaveTimer);
    this.autosaveTimer = setTimeout(() => this.flushAutosave(), this.data.autosave_ms || 500);
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

    el("div", "ann-heading", side).textContent = "Labels";
    this.legendEl = el("div", "ann-legend", side);

    el("div", "ann-heading", side).textContent = "Selection";
    this.inspectorEl = el("div", "ann-inspector", side);

    const view = el("div", "ann-row ann-tools", side);
    this.boxesBtn = this.button(view, "Boxes", "Hide or show boxes (H)", () => this.toggleBoxes());
    this.chipsBtn = this.button(view, "Labels", "Show every label (L)", () => this.toggleChips());
    this.button(view, "Fit", "Fit the screenshot (F)", () => this.fit());
    this.button(view, "Centre", "Centre the screenshot, keeping the zoom (C)", () => this.centre());
    this.button(view, "?", "Shortcuts (?)", () => this.toggleHelp());
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
    this.listeners = [];
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
    this.on(document, "pointerdown", (event) => {
      this.active = event.composedPath().includes(this.wrap);
      this.wrap.classList.toggle("ann-inactive", !this.active);
    });
    this.resizeObserver = new ResizeObserver(() => {
      if (!this.fitted) this.fit();
    });
    this.resizeObserver.observe(viewport);
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
    const low = (this.fitZoom || this.view.zoom) * 0.5;
    const zoom = clamp(this.view.zoom * factor, low, MAX_ZOOM);
    const applied = zoom / this.view.zoom;
    this.view = { zoom, x: px - (px - this.view.x) * applied, y: py - (py - this.view.y) * applied };
    this.applyView();
  }

  toImage(event) {
    const rect = this.viewport.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left - this.view.x) / this.view.zoom,
      y: (event.clientY - rect.top - this.view.y) / this.view.zoom,
    };
  }

  boxesAt(point) {
    const pad = 2 / this.view.zoom;
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
    if (this.selected.size === 1) candidates.push(this.byId([...this.selected][0]));
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

  clampBox(box) {
    const width = this.data.width;
    const height = this.data.height;
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
    box.source = "manual";
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
    this.active = true;
    this.wrap.classList.remove("ann-inactive");
    this.viewport.focus({ preventScroll: true });
    if (event.button === 2) return; // keep the browser's menu (Save image as gives the clean screenshot)
    event.preventDefault();
    const point = this.toImage(event);
    if (event.button === 1 || this.spaceDown) {
      this.drag = { kind: "pan", startX: event.clientX, startY: event.clientY, view: { ...this.view } };
    } else if (!this.showBoxes) {
      return;
    } else {
      const handle = this.handleAt(point);
      const under = this.boxesAt(point);
      if (handle) {
        this.select(handle.box.id, false);
        this.drag = { kind: "resize", handle: handle.handle, start: point, box: { ...handle.box }, id: handle.box.id };
      } else if (under.length) {
        let target = under[0];
        if (event.altKey && under.length > 1) {
          const current = under.findIndex((box) => this.selected.has(box.id));
          target = under[(current + 1) % under.length];
        }
        if (event.shiftKey) {
          if (this.selected.has(target.id)) this.selected.delete(target.id);
          else this.selected.add(target.id);
        } else if (!this.selected.has(target.id) || event.altKey) {
          this.select(target.id, false);
        }
        const originals = [...this.selected].map((id) => ({ ...this.byId(id) }));
        this.drag = { kind: "move", start: point, originals };
      } else {
        if (!event.shiftKey) this.selected.clear();
        this.drag = { kind: "draw", start: point };
      }
    }
    this.viewport.setPointerCapture(event.pointerId);
    this.drag.moved = false;
    this.renderAll();
  }

  pointerMove(event) {
    const point = this.toImage(event);
    const drag = this.drag;
    if (!drag) {
      if (!this.showBoxes) return;
      const handle = this.handleAt(point);
      const under = this.boxesAt(point);
      this.setHover(handle ? handle.box.id : under.length ? under[0].id : null);
      this.viewport.style.cursor = this.spaceDown
        ? "grab"
        : handle
          ? HANDLE_CURSORS[handle.handle]
          : under.length
            ? "move"
            : "crosshair";
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
    if (!drag.moved && Math.hypot(dx, dy) * this.view.zoom < 3) return;
    if (!drag.moved && drag.kind !== "draw") this.snapshot();
    drag.moved = true;
    if (drag.kind === "move") {
      for (const original of drag.originals) {
        const box = this.byId(original.id);
        if (!box) continue;
        box.x = original.x + dx;
        box.y = original.y + dy;
        this.clampBox(box);
        this.markEdited(box);
        this.positionBox(box);
      }
    } else if (drag.kind === "resize") {
      const box = this.byId(drag.id);
      if (!box) return;
      const start = drag.box;
      let left = start.x;
      let top = start.y;
      let right = start.x + start.w;
      let bottom = start.y + start.h;
      if (drag.handle.includes("w")) left += dx;
      if (drag.handle.includes("e")) right += dx;
      if (drag.handle.includes("n")) top += dy;
      if (drag.handle.includes("s")) bottom += dy;
      left = clamp(left, 0, this.data.width);
      right = clamp(right, 0, this.data.width);
      top = clamp(top, 0, this.data.height);
      bottom = clamp(bottom, 0, this.data.height);
      box.x = Math.min(left, right);
      box.y = Math.min(top, bottom);
      box.w = Math.max(1, Math.abs(right - left));
      box.h = Math.max(1, Math.abs(bottom - top));
      this.markEdited(box);
      this.positionBox(box);
    } else if (drag.kind === "draw") {
      const left = clamp(Math.min(drag.start.x, point.x), 0, this.data.width);
      const top = clamp(Math.min(drag.start.y, point.y), 0, this.data.height);
      const right = clamp(Math.max(drag.start.x, point.x), 0, this.data.width);
      const bottom = clamp(Math.max(drag.start.y, point.y), 0, this.data.height);
      drag.rect = { x: left, y: top, w: right - left, h: bottom - top };
      Object.assign(this.drawEl.style, {
        left: `${left}px`,
        top: `${top}px`,
        width: `${right - left}px`,
        height: `${bottom - top}px`,
        borderColor: this.colors[this.currentLabel] || "#fff",
      });
      this.drawEl.hidden = false;
    }
  }

  pointerUp(event) {
    const drag = this.drag;
    this.drag = null;
    if (this.viewport.hasPointerCapture(event.pointerId)) this.viewport.releasePointerCapture(event.pointerId);
    this.drawEl.hidden = true;
    if (!drag) return;
    if (drag.kind === "draw" && drag.moved && drag.rect && drag.rect.w >= MIN_BOX_PX && drag.rect.h >= MIN_BOX_PX) {
      this.snapshot();
      const box = { id: this.makeId(), label: this.currentLabel, ...drag.rect, score: null, source: "manual" };
      this.boxes.push(box);
      this.select(box.id, false);
      this.changed();
    } else if ((drag.kind === "move" || drag.kind === "resize") && drag.moved) {
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
      this.boxes = this.history.pop() || this.boxes;
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
    this.zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX, event.clientY);
  }

  // ---- keyboard -------------------------------------------------------------------------------------------

  keyDown(event) {
    if (!this.active || !this.data || isTyping(event)) return;
    const key = event.key;
    const ctrl = event.ctrlKey || event.metaKey;
    let handled = true;
    if (key === " ") {
      this.spaceDown = true;
      this.viewport.style.cursor = "grab";
    } else if (ctrl && key.toLowerCase() === "z") {
      if (event.shiftKey) this.redo();
      else this.undo();
    } else if (ctrl && key.toLowerCase() === "y") {
      this.redo();
    } else if (ctrl && key.toLowerCase() === "d") {
      this.duplicate();
    } else if (ctrl && key.toLowerCase() === "a") {
      this.selected = new Set(this.boxes.map((box) => box.id));
      this.renderAll();
    } else if (ctrl) {
      handled = false; // leave copy, paste, reload … to the browser
    } else if (key === "Escape") {
      if (this.drag) this.cancelDrag();
      else if (!this.helpEl.hidden) this.toggleHelp();
      else {
        this.selected.clear();
        this.renderAll();
      }
    } else if (key === "Delete" || key === "Backspace") {
      this.deleteSelected();
    } else if (key.startsWith("Arrow")) {
      this.nudge(key, event.shiftKey ? 10 : 1, event.altKey);
    } else if (key === "Tab") {
      this.cycle(event.shiftKey ? -1 : 1);
    } else if (key === "Enter") {
      this.act(event.shiftKey ? "toggle_review" : "review_next");
    } else if (key === "n" || key === "N" || key === "]") {
      this.act("next");
    } else if (key === "p" || key === "P" || key === "[") {
      this.act("prev");
    } else if (key === "h" || key === "H") {
      this.toggleBoxes();
    } else if (key === "l" || key === "L") {
      this.toggleChips();
    } else if (key === "f" || key === "F") {
      this.fit();
    } else if (key === "c" || key === "C") {
      this.centre();
    } else if (key === "," || key === "<" || key === "." || key === ">") {
      const step = event.shiftKey ? SCALE_STEP_SHIFT_PX : SCALE_STEP_PX;
      this.scaleSelected(key === "," || key === "<" ? -step : step);
    } else if (key === "+" || key === "=") {
      if (this.selected.size) this.scaleSelected(SCALE_STEP_PX);
      else this.zoomCentre(1.25);
    } else if (key === "-" || key === "_") {
      if (this.selected.size) this.scaleSelected(-SCALE_STEP_PX);
      else this.zoomCentre(0.8);
    } else if (key === "?") {
      this.toggleHelp();
    } else {
      const label = this.labels.find((item) => item.hotkey && item.hotkey === key);
      if (label) this.useLabel(label.name);
      else handled = false;
    }
    if (handled) {
      event.preventDefault();
      event.stopPropagation(); // Streamlit's own page shortcuts must not also fire
    }
  }

  zoomCentre(factor) {
    const rect = this.viewport.getBoundingClientRect();
    this.zoomAt(factor, rect.left + rect.width / 2, rect.top + rect.height / 2);
  }

  // ---- edits ----------------------------------------------------------------------------------------------

  select(id, add) {
    if (!add) this.selected.clear();
    if (id) this.selected.add(id);
  }

  useLabel(name) {
    const boxes = [...this.selected].map((id) => this.byId(id)).filter(Boolean);
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
    const boxes = [...this.selected].map((id) => this.byId(id)).filter(Boolean);
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
        source: "manual",
      };
      this.clampBox(copy);
      this.boxes.push(copy);
      this.selected.add(copy.id);
    }
    this.changed();
    this.renderAll();
  }

  nudge(key, step, resize) {
    const boxes = [...this.selected].map((id) => this.byId(id)).filter(Boolean);
    if (!boxes.length) return;
    this.snapshot();
    const dx = key === "ArrowLeft" ? -step : key === "ArrowRight" ? step : 0;
    const dy = key === "ArrowUp" ? -step : key === "ArrowDown" ? step : 0;
    for (const box of boxes) {
      if (resize) {
        box.w += dx;
        box.h += dy;
      } else {
        box.x += dx;
        box.y += dy;
      }
      this.clampBox(box);
      this.markEdited(box);
    }
    this.changed();
    this.renderAll();
  }

  scaleSelected(step) {
    // Grow (step > 0) or shrink every side of the selected boxes by step source px, so each keeps its centre:
    // the classical map-node boxes are fixed squares, often a little large for the map node.
    const boxes = [...this.selected].map((id) => this.byId(id)).filter(Boolean);
    if (!boxes.length) return;
    const now = Date.now();
    const selection = [...this.selected].sort().join(" ");
    if (now - this.lastScale.at > SCALE_UNDO_MS || this.lastScale.selection !== selection) this.snapshot();
    this.lastScale = { at: now, selection };
    for (const box of boxes) {
      const cx = box.x + box.w / 2;
      const cy = box.y + box.h / 2;
      box.w = Math.max(MIN_BOX_PX, box.w + 2 * step);
      box.h = Math.max(MIN_BOX_PX, box.h + 2 * step);
      box.x = cx - box.w / 2;
      box.y = cy - box.h / 2;
      this.clampBox(box);
      this.markEdited(box);
    }
    this.changed();
    this.renderAll();
  }

  cycle(step) {
    if (!this.boxes.length) return;
    const order = [...this.boxes].sort((a, b) => a.y - b.y || a.x - b.x);
    const current = order.findIndex((box) => this.selected.has(box.id));
    const index = current < 0 ? (step > 0 ? 0 : order.length - 1) : (current + step + order.length) % order.length;
    const box = order[index];
    this.select(box.id, false);
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
    const margin = 24;
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
  }

  setHover(id) {
    if (this.hoverId === id) return;
    const old = this.hoverId && this.layer.querySelector(`[data-id="${CSS.escape(this.hoverId)}"]`);
    if (old) old.classList.remove("hover");
    this.hoverId = id;
    const node = id && this.layer.querySelector(`[data-id="${CSS.escape(id)}"]`);
    if (node) node.classList.add("hover");
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
      node.style.setProperty("--c", this.colors[box.label] || "#ffffff");
      if (box.source === "manual") node.classList.add("manual");
      if (this.selected.has(box.id)) node.classList.add("selected");
      if (box.id === this.hoverId) node.classList.add("hover");
      const chip = el("span", "ann-chip", node);
      chip.textContent = box.label;
      for (const handle of HANDLES) el("span", `ann-handle ${handle}`, node);
      this.positionBox(box, node);
    }
  }

  positionBox(box, node) {
    const target = node || this.layer.querySelector(`[data-id="${CSS.escape(box.id)}"]`);
    if (!target) return;
    target.style.left = `${box.x}px`;
    target.style.top = `${box.y}px`;
    target.style.width = `${box.w}px`;
    target.style.height = `${box.h}px`;
    if (node) return;
    if (box.source === "manual") target.classList.add("manual");
  }

  renderSide() {
    const data = this.data;
    if (!data) return;
    this.positionEl.textContent = data.position || "";
    this.prevBtn.disabled = !data.has_prev;
    this.nextBtn.disabled = !data.has_next;
    this.reviewState.textContent = data.reviewed ? "✓ Reviewed" : "Not reviewed yet";
    this.reviewState.classList.toggle("ann-ok", Boolean(data.reviewed));
    this.boxesBtn.classList.toggle("ann-off", !this.showBoxes);
    this.chipsBtn.classList.toggle("ann-on", this.showAllChips);
    this.renderStatus();

    const counts = {};
    for (const box of this.boxes) counts[box.label] = (counts[box.label] || 0) + 1;
    this.legendEl.replaceChildren();
    for (const label of this.labels) {
      const row = el("button", "ann-label", this.legendEl);
      row.type = "button";
      row.title = this.selected.size ? `Label the selected boxes ${label.name}` : `Draw ${label.name} boxes`;
      if (label.name === this.currentLabel) row.classList.add("current");
      el("span", "ann-key", row).textContent = label.hotkey || "·";
      const swatch = el("span", "ann-swatch", row);
      swatch.style.background = label.color;
      el("span", "ann-name", row).textContent = label.name;
      el("span", "ann-count", row).textContent = String(counts[label.name] || 0);
      row.addEventListener("click", () => this.useLabel(label.name));
    }
    this.renderInspector();
  }

  renderStatus() {
    if (!this.statusEl || !this.data) return;
    const saved = (this.data.saved_seq || 0) >= this.seq;
    const waiting = this.seq !== this.sentSeq;
    this.statusEl.textContent = `${this.boxes.length} boxes · ${saved ? "saved" : waiting ? "editing…" : "saving…"}`;
    this.statusEl.classList.toggle("ann-ok", saved);
  }

  renderInspector() {
    const panel = this.inspectorEl;
    panel.replaceChildren();
    const boxes = [...this.selected].map((id) => this.byId(id)).filter(Boolean);
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
    const box = boxes[0];
    const select = el("select", "ann-select", panel);
    for (const label of this.labels) {
      const option = el("option", "", select);
      option.value = label.name;
      option.textContent = label.hotkey ? `${label.hotkey}  ${label.name}` : label.name;
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
    const info = el("p", "ann-muted", panel);
    const score = box.score === null || box.score === undefined ? "" : ` · score ${Number(box.score).toFixed(3)}`;
    info.textContent = `${box.source || "manual"}${score}`;
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
