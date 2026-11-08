const W = 256, H = 384, SAVE_DELAY = 150, LINE_HEIGHT = 18, REQUEST_TIMEOUT = 4000;
const $ = id => document.getElementById(id);
const screens = $("screens"), overlay = $("overlay");

// The preview shows a hinge between the screens. Layouts never see it: these
// convert DS rows to preview rows and back, and rows in the hinge land on the seam.
const SEAM = H / 2;
let HINGE = 101, VIEW_H = H + HINGE;    // Set by the chosen shell.
const viewTop = y => y >= SEAM ? y + HINGE : y;
const viewBottom = y => y > SEAM ? y + HINGE : y;
const fromView = row => row <= SEAM ? row : Math.max(SEAM, row - HINGE);
const { animate, stagger } = window.Motion;
const { computePosition, offset, flip, shift, arrow } = window.FloatingUIDOM;
const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const spring = { type: "spring", bounce: 0.35, duration: 0.4 };

let layout = { elements: [] }, catalog = { schema: {}, files: [], tokens: [] };
let selectedId = null, undoStack = [], redoStack = [];
let saveTimer = null, saving = false, saveAgain = false, brightnessReady = false;
let revision = 0, unsaved = false, writing = 0, lastWrite = Promise.resolve(), pulling = false;
const collapsedLayers = new Set();
try { JSON.parse(localStorage.getItem("collapsedLayers") || "[]").forEach(id => collapsedLayers.add(id)); } catch {}
let frameUrl = null, frameLoading = false, frameWanted = false, refreshing = false;
let keepBoxShape = false, jsonDirty = false, soundOn = true, openMenu = null;

const selected = () => layout.elements.find(e => e.id === selectedId);
const clone = value => JSON.parse(JSON.stringify(value));
const fileUrl = reference => `/api/file/${encodeURIComponent(reference)}`;
const canCrop = element => element.type === "image" || element.type === "animation";

function pop(node, from = 0.9) {
  if (!calm) animate(node, { opacity: [0, 1], scale: [from, 1] }, spring);
}

// Sound

const play = name => Effects.play(name);

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("themeButton").textContent = theme === "dark" ? "Light" : "Dark";
}

function setSound(on) {
  soundOn = on;
  Effects.setSound(on);
  $("soundButton").textContent = on ? "Sound on" : "Sound off";
  $("soundButton").setAttribute("aria-pressed", String(on));
  try { localStorage.setItem("sound", on ? "1" : "0"); } catch {}
}

// Messages

function toast(text, isError = false) {
  const node = document.createElement("div");
  node.className = `toast${isError ? " error" : ""}`;
  node.textContent = text;
  $("toasts").replaceChildren(node);
  if (!calm) animate(node, { y: [24, 0], opacity: [0, 1] }, spring);
  setTimeout(() => {
    if (node.isConnected) animate(node, { opacity: 0 }, { duration: 0.25 }).finished.then(() => node.remove());
  }, isError ? 5000 : 1800);
}

function confirmDialog(text) {
  return new Promise(resolve => {
    $("modalText").textContent = text;
    $("modal").hidden = false;
    pop($("modal").firstElementChild);
    $("modalNo").focus();
    const finish = answer => {
      $("modal").hidden = true;
      $("modalYes").onclick = $("modalNo").onclick = null;
      play(answer ? "select" : "back");
      resolve(answer);
    };
    $("modalYes").onclick = () => finish(true);
    $("modalNo").onclick = () => finish(false);
  });
}

async function send(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error(body.error || response.statusText), { status: response.status });
  return { body, revision: Number(response.headers.get("X-Layout-Revision")) };
}

const api = async (path, options) => (await send(path, options)).body;

// Popouts

async function placeBubble(bubble, tail, reference, placement) {
  const { x, y, placement: final, middlewareData } = await computePosition(reference, bubble, {
    strategy: "fixed", placement,
    middleware: [offset(14), flip(), shift({ padding: 10 }), arrow({ element: tail })],
  });
  Object.assign(bubble.style, { left: `${x}px`, top: `${y}px` });

  const side = final.split("-")[0];
  const edge = { top: "bottom", bottom: "top", left: "right", right: "left" }[side];
  const turn = { top: -45, right: 45, bottom: 135, left: 225 }[side];
  const { x: tailX, y: tailY } = middlewareData.arrow;
  Object.assign(tail.style, {
    left: tailX != null ? `${tailX}px` : "", top: tailY != null ? `${tailY}px` : "",
    right: "", bottom: "", [edge]: "-9px", transform: `rotate(${turn}deg)`,
  });
}

function toggleMenu(menu, button, tail, placement) {
  const open = menu.hidden;
  closeMenu();
  if (!open) return;
  menu.hidden = false;
  button.setAttribute("aria-expanded", "true");
  openMenu = { menu, button };
  placeBubble(menu, tail, button, placement);
  pop(menu);
  if (menu === $("addMenu") && !calm) {
    animate(menu.querySelectorAll("button"), { opacity: [0, 1], y: [8, 0] }, { delay: stagger(0.02), duration: 0.2 });
  }
}

function closeMenu() {
  if (!openMenu) return;
  openMenu.menu.hidden = true;
  openMenu.button.setAttribute("aria-expanded", "false");
  openMenu = null;
}

// The inspector points at the selected element from beside the console, or if that
// won't fit, from beside the screens, where it only covers the shell's buttons.
function inspectorReference(element) {
  const shell = document.querySelector(".console").getBoundingClientRect();
  const bounds = screens.getBoundingClientRect();
  const fits = shell.right + $("inspector").offsetWidth + 24 <= window.innerWidth;
  const edge = fits ? shell.right : bounds.right;
  const top = bounds.top + viewTop(element.y + element.h / 2) / VIEW_H * bounds.height;
  return { getBoundingClientRect: () => ({ x: edge, y: top, left: edge, right: edge, top, bottom: top, width: 0, height: 0 }) };
}

function placeInspector() {
  const element = selected();
  if (element && !$("inspector").hidden) placeBubble($("inspector"), $("inspectorTail"), inspectorReference(element), "right");
}

// Editing

function remember() {
  undoStack.push(clone(layout));
  if (undoStack.length > 100) undoStack.shift();
  redoStack = [];
  updateHistoryButtons();
}

function updateHistoryButtons() {
  $("undo").disabled = !undoStack.length;
  $("redo").disabled = !redoStack.length;
}

function restore(from, to) {
  if (!from.length) return;
  to.push(clone(layout));
  layout = from.pop();
  if (!selected()) selectedId = null;
  updateHistoryButtons();
  renderAll();
  saveSoon();
  play("back");
}

function saveSoon() {
  unsaved = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { saveTimer = null; save(); }, SAVE_DELAY);
}

// One request at a time, so an older layout can never land after a newer one, and
// each carries the revision the one before it got back, so a tab can't clash with itself.
function writeLayout(path, body) {
  writing++;
  const post = async () => {
    const reply = await send(path, { method: "POST", headers: { "X-Layout-Revision": revision }, body });
    revision = reply.revision;
    return reply.body;
  };
  const result = lastWrite.then(post);
  lastWrite = result.catch(() => {}).finally(() => { writing--; });
  return result;
}

async function save() {
  if (saving) { saveAgain = true; return; }
  saving = true;
  try {
    await writeLayout("/api/layout", JSON.stringify(layout));
    if (!saveTimer && !saveAgain) unsaved = false;
    refreshFrame();
  } catch (error) {
    if (error.status === 409) await pullLayout(); else toast(error.message, true);
  }
  saving = false;
  if (saveAgain) { saveAgain = false; save(); }
}

// Takes the server's layout after another tab changed it. Edits this tab couldn't
// save go on the undo stack, so they aren't lost.
async function pullLayout() {
  if (pulling) return;
  pulling = true;
  const hadEdits = unsaved;
  try {
    const latest = await send("/api/layout");
    if (unsaved && !hadEdits) return;  // The save of this new edit will get a 409.
    if (JSON.stringify(latest.body) !== JSON.stringify(layout)) {
      remember();
      layout = latest.body;
      if (!selected()) selectedId = null;
      renderAll();
      refreshFrame();
      if (hadEdits) toast("Another tab changed the layout, so your last edit here was not saved. Undo brings it back, replacing theirs.", true);
      else toast("Layout updated from another tab");
    }
    revision = latest.revision;
    unsaved = false;
    if (jsonDirty) $("jsonError").textContent = "Another tab changed the layout. Apply replaces it with this text. Revert shows the new layout.";
  } catch {
    // The next poll tries again.
  } finally {
    pulling = false;
  }
}

function uniqueId(type) {
  for (let n = 1; ; n++) {
    const id = `${type}_${n}`;
    if (!layout.elements.some(e => e.id === id)) return id;
  }
}

function addElement(type, props = {}) {
  const schema = catalog.schema[type];
  remember();
  const values = Object.fromEntries(schema.props.map(p => [p.key, p.default]));
  const element = {
    id: uniqueId(type), type, x: 60, y: 200, w: schema.size[0], h: schema.size[1],
    hidden: false, locked: false, props: { ...values, ...props },
  };
  layout.elements.push(element);
  select(element.id);
  saveSoon();
}

function removeSelected() {
  if (!selected()) return;
  remember();
  layout.elements = layout.elements.filter(e => e.id !== selectedId);
  selectedId = null;
  renderAll();
  saveSoon();
  play("back");
}

function moveInOrder(step) {
  const index = layout.elements.indexOf(selected());
  const target = index + step;
  if (index < 0 || target < 0 || target >= layout.elements.length) return;
  remember();
  const [element] = layout.elements.splice(index, 1);
  layout.elements.splice(target, 0, element);
  renderAll();
  saveSoon();
}

function change(mutate) {
  if (!selected()) return;
  remember();
  mutate(selected());
  // Turning the lock on, or a new crop, should take effect straight away.
  const element = selected();
  if (element.props?.pixel_lock === "yes") {
    loadArtInfo(element.props.file).then(() => {
      const snapped = snapToPixels(element, element.w);
      if (snapped && (snapped.w !== element.w || snapped.h !== element.h)) {
        Object.assign(element, snapped);
        renderAll();
        saveSoon();
      }
    }).catch(() => {});
  }
  renderOverlay();
  renderList();
  renderJson();
  saveSoon();
}

// Art info, cached so that dragging never waits on the server.

const artInfo = new Map();

async function loadArtInfo(reference) {
  if (!artInfo.has(reference)) {
    artInfo.set(reference, await api(`/api/pixel-scale?file=${encodeURIComponent(reference)}`));
  }
  return artInfo.get(reference);
}

function cropOf(element, naturalWidth, naturalHeight) {
  const { crop_x: x, crop_y: y, crop_w: w, crop_h: h } = element.props;
  return w && h ? { x, y, w, h } : { x: 0, y: 0, w: naturalWidth, h: naturalHeight };
}

// Keeps an element at a whole multiple of the art's own pixels.
function snapToPixels(element, width) {
  const info = artInfo.get(element.props.file);
  if (!info) return null;
  const crop = cropOf(element, info.width, info.height);
  const unitW = crop.w / info.scale, unitH = crop.h / info.scale;
  const limit = Math.max(1, Math.floor(Math.min(W / unitW, H / unitH)));
  const multiple = Math.max(1, Math.min(limit, Math.round(width / unitW)));
  return { w: Math.round(unitW * multiple), h: Math.round(unitH * multiple) };
}

// Drawing the editor

function placeBox(node, e) {
  node.style.left = `${e.x / W * 100}%`;
  node.style.top = `${e.y / H * 100}%`;
  node.style.width = `${e.w / W * 100}%`;
  node.style.height = `${e.h / H * 100}%`;
}

// Boxes live in the overlay, so unlike placeBox they span the hinge.
function placeHandle(node, e) {
  const top = viewTop(e.y);
  node.style.left = `${e.x / W * 100}%`;
  node.style.top = `${top / VIEW_H * 100}%`;
  node.style.width = `${e.w / W * 100}%`;
  node.style.height = `${(viewBottom(e.y + e.h) - top) / VIEW_H * 100}%`;
}

function renderAnimations() {
  const wanted = layout.elements.filter(e => e.type === "animation" && !e.hidden);
  const [top, bottom] = document.querySelectorAll(".animations");
  top.replaceChildren(...wanted.filter(e => e.y < SEAM).map(animationView));
  bottom.replaceChildren(...wanted.filter(e => e.y + e.h > SEAM).map(animationView));
}

function animationView(e) {
  const view = document.createElement("div");
  view.className = "anim-view";
  placeBox(view, e);

  const image = document.createElement("img");
  image.src = fileUrl(e.props.file);
  image.alt = "";
  image.onload = () => {
    // Show only the cropped part, scaled to fill the element.
    const crop = cropOf(e, image.naturalWidth, image.naturalHeight);
    image.style.width = `${image.naturalWidth / crop.w * 100}%`;
    image.style.height = `${image.naturalHeight / crop.h * 100}%`;
    image.style.left = `${-crop.x / crop.w * 100}%`;
    image.style.top = `${-crop.y / crop.h * 100}%`;
  };
  view.append(image);
  return view;
}

function renderOverlay() {
  overlay.replaceChildren(...layout.elements.filter(e => !e.hidden).map(e => {
    const box = document.createElement("div");
    box.className = "box";
    box.dataset.id = e.id;
    box.classList.toggle("locked", e.locked);
    box.classList.toggle("selected", e.id === selectedId);
    placeHandle(box, e);
    if (e.id === selectedId && !e.locked && !catalog.schema[e.type].fixed_size) {
      for (const corner of ["nw", "ne", "sw", "se"]) {
        const handle = document.createElement("div");
        handle.className = `handle ${corner}`;
        handle.dataset.corner = corner;
        box.append(handle);
      }
    }
    return box;
  }));
  renderAnimations();
}

// The tree comes from where things are: an element's parent is the smallest one behind
// it that fully contains it. Layouts stay flat, so moving something re-parents it.
function parentsOf(elements) {
  const inside = (a, b) => a.x >= b.x && a.y >= b.y && a.x + a.w <= b.x + b.w && a.y + a.h <= b.y + b.h;
  const parents = new Map();
  elements.forEach((element, index) => {
    const around = elements.slice(0, index).filter(other => inside(element, other));
    const nearest = around.reduce((best, other) => !best || other.w * other.h <= best.w * best.h ? other : best, null);
    if (nearest) parents.set(element.id, nearest.id);
  });
  return parents;
}

function saveCollapsed() {
  try { localStorage.setItem("collapsedLayers", JSON.stringify([...collapsedLayers])); } catch {}
}

function layerRow(e, depth, hasChildren) {
  const row = document.createElement("div");
  row.className = "item";
  row.classList.toggle("top", depth === 0);
  row.classList.toggle("selected", e.id === selectedId);
  row.classList.toggle("hidden", e.hidden);
  row.dataset.id = e.id;
  row.style.setProperty("--depth", depth);

  const twisty = document.createElement(hasChildren ? "button" : "span");
  twisty.className = "twisty";
  if (hasChildren) {
    const open = !collapsedLayers.has(e.id);
    twisty.textContent = open ? "-" : "+";
    twisty.setAttribute("aria-expanded", String(open));
    twisty.setAttribute("aria-label", `${open ? "Collapse" : "Expand"} ${e.id}`);
    twisty.addEventListener("click", event => {
      event.stopPropagation();
      play("select");
      if (open) collapsedLayers.add(e.id); else collapsedLayers.delete(e.id);
      saveCollapsed();
      renderList();
    });
  }
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = `${e.locked ? "🔒 " : ""}${e.id}`;
  const type = document.createElement("span");
  type.className = "type";
  type.textContent = catalog.schema[e.type].label;
  row.append(twisty, name, type);
  row.addEventListener("click", () => select(e.id));
  return row;
}

function renderList() {
  const parents = parentsOf(layout.elements);
  const children = new Map();
  // Front-most first, matching what you see on screen.
  for (const e of [...layout.elements].reverse()) {
    const parent = parents.get(e.id) ?? null;
    children.set(parent, [...(children.get(parent) ?? []), e]);
  }
  const rows = [];
  const addRows = (parent, depth) => {
    for (const e of children.get(parent) ?? []) {
      rows.push(layerRow(e, depth, children.has(e.id)));
      if (!collapsedLayers.has(e.id)) addRows(e.id, depth + 1);
    }
  };
  addRows(null, 0);
  $("list").replaceChildren(...rows);
}

function field(labelText, control) {
  const label = document.createElement("label");
  label.className = "field";
  label.textContent = labelText;
  label.append(control);
  return label;
}

function switchControl(labelText, checked, onChange) {
  const label = document.createElement("label");
  label.className = "switch";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", () => { play("select"); onChange(input.checked); });
  const track = document.createElement("i");
  label.append(labelText, input, track);
  return label;
}

function propControl(element, prop) {
  // Yes or no reads better as a switch.
  if (prop.kind === "select" && prop.options.join() === "yes,no") {
    return switchControl(prop.label, element.props[prop.key] === "yes",
      on => change(e => { e.props[prop.key] = on ? "yes" : "no"; }));
  }

  if (prop.kind === "swatch") return swatchControl(element, prop);

  let input;
  if (prop.kind === "select" || prop.kind === "file") {
    input = document.createElement("select");
    const options = prop.kind === "file"
      ? catalog.files.filter(f => element.type !== "animation" || f.toLowerCase().endsWith(".gif"))
      : prop.options;
    for (const value of options) input.add(new Option(value, value));
    input.value = element.props[prop.key];
  } else {
    input = document.createElement("input");
    input.type = prop.kind === "color" ? "color" : prop.kind === "number" ? "number" : "text";
    input.value = element.props[prop.key];
  }
  input.addEventListener("change", () => {
    const value = prop.kind === "number" ? Number(input.value) || 0 : input.value;
    change(e => { e.props[prop.key] = value; });
    if (prop.kind === "file") renderInspector();
  });
  return field(prop.label, input);
}

// Options shown as pictures: prop.preview is a file reference with {value} in it, such as the bar art.
function swatchControl(element, prop) {
  const grid = document.createElement("div");
  grid.className = "swatches bars";
  for (const value of prop.options) {
    const swatch = document.createElement("button");
    swatch.className = "shell-swatch";
    swatch.title = value === "theme" ? "Follow the theme" : value;
    swatch.setAttribute("aria-pressed", String(element.props[prop.key] === value));
    if (value === "theme" || !prop.preview) swatch.textContent = value === "theme" ? "T" : value;
    else swatch.style.backgroundImage = `url("${fileUrl(prop.preview.replace("{value}", value))}")`;
    swatch.addEventListener("click", () => { change(e => { e.props[prop.key] = value; }); renderInspector(); });
    grid.append(swatch);
  }
  return field(prop.label, grid);
}

function renderInspector() {
  const inspector = $("inspector"), fields = $("fields"), element = selected();
  if (!element) { inspector.hidden = true; return; }

  const wasHidden = inspector.hidden;
  const schema = catalog.schema[element.type];
  $("inspectorTitle").textContent = `${schema.label}: ${element.id}`;
  fields.replaceChildren();

  const geometry = document.createElement("div");
  geometry.className = "grid4";
  for (const key of ["x", "y", "w", "h"]) {
    const input = document.createElement("input");
    input.type = "number";
    input.value = element[key];
    input.disabled = Boolean(schema.fixed_size) && (key === "w" || key === "h");
    input.addEventListener("change", () => change(e => { e[key] = Number(input.value) || 0; }));
    geometry.append(field(key.toUpperCase(), input));
  }
  fields.append(geometry);

  for (const prop of schema.props) {
    if (prop.key.startsWith("crop_")) continue;   // Edited with the cropper below
    const control = propControl(element, prop);
    fields.append(control);
    if (element.type === "text" && prop.key === "text") {
      const input = control.querySelector("input");
      const tokens = document.createElement("div");
      tokens.className = "tokens";
      for (const token of catalog.tokens) {
        const chip = document.createElement("button");
        chip.textContent = token;
        chip.addEventListener("click", () => {
          input.value += `{${token}}`;
          input.dispatchEvent(new Event("change"));
        });
        tokens.append(chip);
      }
      fields.append(tokens);
    }
  }

  if (canCrop(element)) fields.append(buildCropper(element));

  const actions = document.createElement("div");
  actions.className = "row";
  const action = (text, onClick, danger) => {
    const button = document.createElement("button");
    button.className = "ds-button";
    if (danger) button.style.color = "var(--red)";
    button.textContent = text;
    button.addEventListener("click", onClick);
    return button;
  };
  const toggle = key => () => { change(e => { e[key] = !e[key]; }); renderInspector(); };
  actions.append(action(element.hidden ? "Show" : "Hide", toggle("hidden")),
                 action(element.locked ? "Unlock" : "Lock", toggle("locked")),
                 action("Delete", removeSelected, true));
  fields.append(actions);

  inspector.hidden = false;
  placeInspector();
  if (wasHidden) pop(inspector);
}

// Cropping

function buildCropper(element) {
  const holder = document.createElement("div");
  const title = document.createElement("label");
  title.className = "field";
  title.textContent = "Crop";
  const stage = document.createElement("div");
  stage.className = "cropper";
  const image = document.createElement("img");
  image.alt = "Source image";
  image.src = fileUrl(element.props.file);
  const area = document.createElement("div");
  area.className = "crop-area";
  stage.append(image, area);

  const size = document.createElement("p");
  size.className = "hint";
  const buttons = document.createElement("div");
  buttons.className = "chips";
  const shape = switchControl("Keep box shape", keepBoxShape, on => { keepBoxShape = on; });
  holder.append(title, stage, buttons, shape, size);

  image.onload = () => {
    placeInspector();
    const natural = { w: image.naturalWidth, h: image.naturalHeight };
    let crop = cropOf(element, natural.w, natural.h);

    const show = () => {
      area.style.left = `${crop.x / natural.w * 100}%`;
      area.style.top = `${crop.y / natural.h * 100}%`;
      area.style.width = `${crop.w / natural.w * 100}%`;
      area.style.height = `${crop.h / natural.h * 100}%`;
      size.textContent = `Source ${natural.w}×${natural.h}, crop ${crop.w}×${crop.h}`;
    };

    const commit = () => change(e => {
      const info = artInfo.get(e.props.file);
      const locked = e.props.pixel_lock === "yes" && info && !keepBoxShape;
      if (locked) {
        // Pixels keep their size, so the box follows the crop, and what's kept stays put.
        const before = cropOf(e, natural.w, natural.h);
        const zoom = Math.max(1, Math.round(e.w / (before.w / info.scale))) / info.scale;
        const whole = value => Math.round(value / info.scale) * info.scale;
        const x = whole(crop.x), y = whole(crop.y);
        crop = {
          x, y,
          w: Math.max(info.scale, Math.min(whole(crop.w), natural.w - x)),
          h: Math.max(info.scale, Math.min(whole(crop.h), natural.h - y)),
        };
        e.x += Math.round((crop.x - before.x) * zoom);
        e.y += Math.round((crop.y - before.y) * zoom);
        e.w = Math.round(crop.w * zoom);
        e.h = Math.round(crop.h * zoom);
      }
      Object.assign(e.props, { crop_x: crop.x, crop_y: crop.y, crop_w: crop.w, crop_h: crop.h });
      if (!locked && e.props.lock_aspect === "yes" && !keepBoxShape) e.h = Math.max(1, Math.round(e.w * crop.h / crop.w));
    });

    const addButton = (text, onClick) => {
      const button = document.createElement("button");
      button.textContent = text;
      button.addEventListener("click", onClick);
      buttons.append(button);
    };

    addButton("Full image", () => { crop = { x: 0, y: 0, w: natural.w, h: natural.h }; show(); commit(); renderInspector(); });

    // Whole multiples of the art's own pixels stay crisp.
    loadArtInfo(element.props.file).then(({ scale }) => {
      for (const multiple of [1, 2, 3]) {
        addButton(`${multiple}×`, () => {
          const w = Math.round(crop.w / scale * multiple), h = Math.round(crop.h / scale * multiple);
          if (w > W || h > H) { toast(`${w}×${h} is larger than the screen`, true); return; }
          change(e => { e.w = w; e.h = h; });
          renderInspector();
        });
      }
    }).catch(() => {});

    // A crop of the whole image can't move, and leaves nowhere else to start drawing.
    const isWhole = () => crop.w >= natural.w && crop.h >= natural.h;
    area.addEventListener("pointerdown", event => startCropDrag(event, isWhole() ? "draw" : "move"));
    for (const corner of ["nw", "ne", "sw", "se"]) {
      const handle = document.createElement("span");
      handle.className = `crop-handle ${corner}`;
      handle.addEventListener("pointerdown", event => {
        event.stopPropagation();
        // Resizing is drawing from the opposite corner.
        startCropDrag(event, "draw", {
          x: corner.includes("w") ? crop.x + crop.w : crop.x,
          y: corner.includes("n") ? crop.y + crop.h : crop.y,
        });
      });
      area.append(handle);
    }
    stage.addEventListener("pointerdown", event => { if (event.target === stage) startCropDrag(event, "draw"); });

    function startCropDrag(event, mode, anchor) {
      event.preventDefault();
      const bounds = stage.getBoundingClientRect();
      const toSource = (x, y) => ({
        x: Math.round((x - bounds.left) / bounds.width * natural.w),
        y: Math.round((y - bounds.top) / bounds.height * natural.h),
      });
      const origin = anchor || toSource(event.clientX, event.clientY);
      const start = { ...crop };
      let moved = false;
      const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

      const onMove = moveEvent => {
        moved = true;
        const point = toSource(moveEvent.clientX, moveEvent.clientY);
        if (mode === "move") {
          crop.x = clamp(start.x + point.x - origin.x, 0, natural.w - crop.w);
          crop.y = clamp(start.y + point.y - origin.y, 0, natural.h - crop.h);
        } else {
          const end = { x: clamp(point.x, 0, natural.w), y: clamp(point.y, 0, natural.h) };
          const width = Math.abs(end.x - origin.x);
          const height = keepBoxShape ? width * element.h / element.w : Math.abs(end.y - origin.y);
          const top = end.y < origin.y && keepBoxShape ? origin.y - height : Math.min(origin.y, end.y);
          crop = { x: Math.min(origin.x, end.x), y: clamp(Math.round(top), 0, natural.h - 1), w: Math.max(1, width), h: Math.max(1, Math.round(height)) };
          crop.h = Math.min(crop.h, natural.h - crop.y);
        }
        show();
      };

      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        if (!moved) return;
        commit();
        renderInspector();
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    }

    show();
  };
  return holder;
}

// JSON

// Leaves the text alone while it has unapplied edits, so typing is never overwritten.
function renderJson(force = false) {
  if (force || !jsonDirty) {
    $("json").value = JSON.stringify(layout, null, 2);
    jsonDirty = false;
    $("jsonError").textContent = "";
    highlightJson();
  }
}

const escapeHtml = text => text.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

function highlightValue(raw) {
  const text = raw.slice(1, -1);
  if (/^#[0-9a-fA-F]{6}$/.test(text)) {
    return `<span class="swatch" style="background:${text}"></span><span class="tok-string">${escapeHtml(raw)}</span>`;
  }
  const marked = escapeHtml(raw).replace(/\{(\w+)\}/g, (match, name) =>
    catalog.tokens.includes(name) ? `<span class="tok-token">${match}</span>` : match);
  return `<span class="tok-string">${marked}</span>`;
}

function highlightLine(line) {
  let out = "", last = 0;
  for (const match of line.matchAll(/"(?:[^"\\]|\\.)*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?/g)) {
    out += escapeHtml(line.slice(last, match.index));
    last = match.index + match[0].length;
    const [text, colon] = match;
    if (colon) out += `<span class="tok-key">${escapeHtml(text.slice(0, -colon.length))}</span>${colon}`;
    else if (text[0] === '"') out += highlightValue(text);
    else if (/^[a-z]/.test(text)) out += `<span class="tok-bool">${text}</span>`;
    else out += `<span class="tok-number">${text}</span>`;
  }
  return out + escapeHtml(line.slice(last));
}

// Finds which lines belong to each element, from its "id" line to the next one.
function elementLines(lines) {
  const blocks = [];
  lines.forEach((line, index) => {
    const match = /^\s*"id":\s*"([^"]*)"/.exec(line);
    if (match) {
      if (blocks.length) blocks[blocks.length - 1].end = index - 2;
      blocks.push({ id: match[1], start: index - 1, end: lines.length - 1 });
    }
  });
  return blocks;
}

function checkJson(text) {
  try {
    const value = JSON.parse(text);
    if (!Array.isArray(value.elements)) return { message: 'Needs an "elements" list' };
    const seen = new Set();
    for (const element of value.elements) {
      if (!catalog.schema[element?.type]) return { message: `Unknown type "${element?.type}"` };
      if (seen.has(element.id)) return { message: `Duplicate id "${element.id}"` };
      seen.add(element.id);
    }
    return null;
  } catch (error) {
    const position = /position (\d+)/.exec(error.message);
    const line = position ? text.slice(0, Number(position[1])).split("\n").length - 1 : null;
    return { message: error.message, line };
  }
}

function highlightJson() {
  const text = $("json").value, lines = text.split("\n");
  const problem = checkJson(text);
  const block = elementLines(lines).find(b => b.id === selectedId);

  $("jsonView").innerHTML = lines.map((line, index) => {
    const classes = ["line"];
    if (block && index >= block.start && index <= block.end) classes.push("active");
    if (problem && problem.line === index) classes.push("bad");
    return `<span class="${classes.join(" ")}">${highlightLine(line)}</span>`;
  }).join("");

  $("applyJson").disabled = Boolean(problem);
  $("jsonState").textContent = problem
    ? (problem.line != null ? `Line ${problem.line + 1}: ` : "") + problem.message
    : jsonDirty ? "Valid. Apply to send it to the DS." : "Matches the DS.";
  $("jsonState").style.color = problem ? "var(--red)" : "";
  syncScroll();
}

function syncScroll() {
  $("jsonView").scrollTop = $("json").scrollTop;
  $("jsonView").scrollLeft = $("json").scrollLeft;
}

// Moving the caret into an element selects it on the preview.
function selectFromCaret() {
  const box = $("json");
  const line = box.value.slice(0, box.selectionStart).split("\n").length - 1;
  const block = elementLines(box.value.split("\n")).find(b => line >= b.start && line <= b.end);
  if (block && block.id !== selectedId && layout.elements.some(e => e.id === block.id)) {
    selectedId = block.id;
    renderOverlay();
    renderList();
    renderInspector();
    highlightJson();
  }
}

// Selecting on the preview scrolls the JSON to that element.
function revealSelected() {
  const box = $("json");
  const block = elementLines(box.value.split("\n")).find(b => b.id === selectedId);
  if (block) {
    box.scrollTop = Math.max(0, block.start * LINE_HEIGHT - 40);
    syncScroll();
  }
}

function renderAll() {
  renderOverlay();
  renderList();
  renderInspector();
  renderJson();
}

function select(id) {
  if (id && !editing) setEditing(true);
  if (id !== selectedId) play(id ? "select" : "back");
  selectedId = id;
  // Open the branches above it, so it's visible in the list.
  const parents = parentsOf(layout.elements);
  for (let parent = parents.get(id); parent; parent = parents.get(parent)) collapsedLayers.delete(parent);
  saveCollapsed();
  const element = selected();
  if (element && canCrop(element)) loadArtInfo(element.props.file).catch(() => {});
  renderAll();
  highlightJson();
  revealSelected();
}

// Drawer

function showDrawer(tab) {
  const drawer = $("drawer");
  const closing = !drawer.hidden && drawer.dataset.tab === tab;
  const opening = drawer.hidden;
  drawer.hidden = closing;
  drawer.dataset.tab = closing ? "" : tab;
  $("toggleLayers").setAttribute("aria-expanded", String(!closing && tab === "layers"));
  $("toggleJson").setAttribute("aria-expanded", String(!closing && tab === "json"));
  try { localStorage.setItem("drawer", closing ? "" : tab); } catch {}
  play(closing ? "back" : "select");
  if (closing) { requestAnimationFrame(placeInspector); return; }

  const json = tab === "json";
  drawer.classList.toggle("wide", json);
  $("layersPane").hidden = json;
  $("jsonPanel").hidden = !json;
  $("layersTab").setAttribute("aria-selected", String(!json));
  $("jsonTab").setAttribute("aria-selected", String(json));
  $("tabMark").style.transform = "";
  if (!calm) animate($("tabMark"), { x: json ? "100%" : "0%" }, spring);
  else $("tabMark").style.transform = json ? "translateX(100%)" : "";
  if (json) { highlightJson(); revealSelected(); }
  if (opening && !calm) {
    animate(drawer, { x: [40, 0], opacity: [0, 1] }, spring);
    if (!json) animate(drawer.querySelectorAll(".item"), { opacity: [0, 1], x: [8, 0] }, { delay: stagger(0.012), duration: 0.18 });
  }
  requestAnimationFrame(placeInspector);
}

// Dragging on the preview

// Edges and centres pull to the screens' and other elements' edges and centres. Alt places freely.
const SNAP = 4;

function snapTargets(skipId) {
  const xs = [0, W / 2, W], ys = [0, SEAM / 2, SEAM, SEAM * 1.5, H];
  for (const e of layout.elements) {
    if (e.id === skipId || e.hidden) continue;
    xs.push(e.x, e.x + e.w / 2, e.x + e.w);
    ys.push(e.y, e.y + e.h / 2, e.y + e.h);
  }
  return { xs, ys };
}

function nearest(values, targets) {
  let best = null;
  for (const value of values) {
    for (const target of targets) {
      const shift = target - value;
      if (Math.abs(shift) <= SNAP && (!best || Math.abs(shift) < Math.abs(best.shift))) best = { shift, at: target };
    }
  }
  return best;
}

function showGuides(guides) {
  overlay.querySelectorAll(".guide").forEach(node => node.remove());
  for (const { axis, at } of guides) {
    const line = document.createElement("div");
    line.className = `guide ${axis}`;
    if (axis === "x") line.style.left = `${at / W * 100}%`;
    else line.style.top = `${viewBottom(at) / VIEW_H * 100}%`;
    overlay.append(line);
  }
}

function snapMove(live, targets) {
  const guides = [];
  const x = nearest([live.x, live.x + live.w / 2, live.x + live.w], targets.xs);
  if (x) { live.x = Math.round(live.x + x.shift); guides.push({ axis: "x", at: x.at }); }
  const y = nearest([live.y, live.y + live.h / 2, live.y + live.h], targets.ys);
  if (y) { live.y = Math.round(live.y + y.shift); guides.push({ axis: "y", at: y.at }); }
  return guides;
}

function snapResize(live, corner, targets) {
  const guides = [];
  const x = nearest([corner.includes("e") ? live.x + live.w : live.x], targets.xs);
  if (x) {
    const shift = Math.round(x.shift);
    if (corner.includes("e")) live.w = Math.max(1, live.w + shift);
    else { live.x += shift; live.w = Math.max(1, live.w - shift); }
    guides.push({ axis: "x", at: x.at });
  }
  const y = nearest([corner.includes("s") ? live.y + live.h : live.y], targets.ys);
  if (y) {
    const shift = Math.round(y.shift);
    if (corner.includes("s")) live.h = Math.max(1, live.h + shift);
    else { live.y += shift; live.h = Math.max(1, live.h - shift); }
    guides.push({ axis: "y", at: y.at });
  }
  return guides;
}

overlay.addEventListener("pointerdown", event => {
  closeMenu();
  const box = event.target.closest(".box");
  if (!box) { select(null); return; }
  event.preventDefault();

  const corner = event.target.dataset.corner;
  if (box.dataset.id !== selectedId) select(box.dataset.id);
  const element = selected();
  const start = { x: element.x, y: element.y, w: element.w, h: element.h };
  const origin = { x: event.clientX, y: event.clientY };
  const bounds = screens.getBoundingClientRect();
  const unit = bounds.width / W;
  const rowAt = clientY => fromView((clientY - bounds.top) / unit);
  const startRow = rowAt(event.clientY);
  const targets = snapTargets(element.id);
  let moved = false;

  const onMove = moveEvent => {
    const dx = Math.round((moveEvent.clientX - origin.x) / unit);
    const dy = Math.round(rowAt(moveEvent.clientY) - startRow);
    if (!moved && !dx && !dy) return;
    if (!moved) { remember(); moved = true; }

    const live = selected();
    if (!live) return;  // Another tab removed it.
    if (corner) {
      let width = start.w + (corner.includes("e") ? dx : -dx);
      let height = start.h + (corner.includes("s") ? dy : -dy);

      // Shift flips the lock for one drag, either way.
      const locked = live.props.lock_aspect === "yes";
      if (locked !== moveEvent.shiftKey && canCrop(live)) {
        const ratio = start.w / start.h;
        if (Math.abs(dx) >= Math.abs(dy)) height = width / ratio; else width = height * ratio;
      }
      const snapped = live.props.pixel_lock === "yes" ? snapToPixels(live, width) : null;
      live.w = snapped ? snapped.w : Math.max(1, Math.round(width));
      live.h = snapped ? snapped.h : Math.max(1, Math.round(height));
      if (corner.includes("w")) live.x = start.x + start.w - live.w;
      if (corner.includes("n")) live.y = start.y + start.h - live.h;
      // Snapping a corner would break a locked shape.
      const shaped = snapped || (locked !== moveEvent.shiftKey && canCrop(live));
      showGuides(moveEvent.altKey || shaped ? [] : snapResize(live, corner, targets));
    } else {
      live.x = start.x + dx;
      live.y = start.y + dy;
      showGuides(moveEvent.altKey ? [] : snapMove(live, targets));
    }
    const node = overlay.querySelector(`[data-id="${CSS.escape(live.id)}"]`);
    if (node) placeHandle(node, live);
    renderAnimations();
    placeInspector();
    saveSoon();
  };

  const onUp = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    showGuides([]);
    if (moved) { renderList(); renderInspector(); renderJson(); }
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    if (openMenu) closeMenu(); else if (selectedId) select(null); else if (editing) { play("back"); setEditing(false); }
    return;
  }
  if (event.target.matches("input, select, textarea")) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) restore(redoStack, undoStack); else restore(undoStack, redoStack);
    return;
  }
  const element = selected();
  if (!element) return;
  if (event.key === "Delete" || event.key === "Backspace") { event.preventDefault(); removeSelected(); return; }

  const step = event.shiftKey ? 8 : 1;
  const move = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
  if (!move || element.locked) return;
  event.preventDefault();
  change(e => { e.x += move[0]; e.y += move[1]; });
  renderInspector();
});

document.addEventListener("pointerdown", event => {
  if (openMenu && !openMenu.menu.contains(event.target) && !openMenu.button.contains(event.target)) closeMenu();
});
window.addEventListener("resize", placeInspector);
window.addEventListener("scroll", placeInspector, true);

// Toolbar

$("undo").addEventListener("click", () => restore(undoStack, redoStack));
$("redo").addEventListener("click", () => restore(redoStack, undoStack));
$("forward").addEventListener("click", () => moveInOrder(1));
$("back").addEventListener("click", () => moveInOrder(-1));
$("closeInspector").addEventListener("click", () => select(null));
$("toggleLayers").addEventListener("click", () => showDrawer("layers"));
$("toggleJson").addEventListener("click", () => showDrawer("json"));
$("layersTab").addEventListener("click", () => { if ($("drawer").dataset.tab !== "layers") showDrawer("layers"); });
$("jsonTab").addEventListener("click", () => { if ($("drawer").dataset.tab !== "json") showDrawer("json"); });
$("addButton").addEventListener("click", () => { play("select"); toggleMenu($("addMenu"), $("addButton"), $("addTail"), "top"); });
$("brightnessButton").addEventListener("click", () => { play("select"); toggleMenu($("brightnessMenu"), $("brightnessButton"), $("brightnessTail"), "bottom"); });
$("soundButton").addEventListener("click", () => { setSound(!soundOn); play("select"); });
$("themeButton").addEventListener("click", () => {
  play("select");
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch {}
});

$("reset").addEventListener("click", async () => {
  play("back");
  if (!await confirmDialog("Reset to the default layout? Undo can bring yours back.")) return;
  try {
    const fresh = await writeLayout("/api/layout/reset");
    remember();
    layout = fresh;
    selectedId = null;
    renderAll();
    refreshFrame();
    toast("Layout reset");
  } catch (error) {
    if (error.status === 409) await pullLayout();
    toast(error.status === 409 ? "Another tab changed the layout, so it was not reset. Try again." : error.message, true);
  }
});

$("upload").addEventListener("change", async event => {
  const [file] = event.target.files;
  if (!file) return;
  toast("Uploading…");
  try {
    const result = await api(`/api/upload?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
    catalog.files = result.files;
    addElement(file.type === "image/gif" ? "animation" : "image", { file: result.file });
    toast(`Added ${file.name}`);
  } catch (error) {
    toast(error.message, true);
  }
  event.target.value = "";
});

$("brightness").addEventListener("input", () => { $("brightnessValue").textContent = `${$("brightness").value}%`; });
$("brightness").addEventListener("change", () => api("/api/brightness", {
  method: "POST", body: JSON.stringify({ level: Number($("brightness").value) }),
}));

$("json").addEventListener("input", () => { jsonDirty = true; highlightJson(); });
$("json").addEventListener("scroll", syncScroll);
$("json").addEventListener("click", selectFromCaret);
$("json").addEventListener("keyup", selectFromCaret);
$("json").addEventListener("keydown", event => {
  if (event.key === "Tab") {
    event.preventDefault();
    const box = event.target;
    box.setRangeText("  ", box.selectionStart, box.selectionEnd, "end");
    box.dispatchEvent(new Event("input"));
  }
});
$("revertJson").addEventListener("click", () => renderJson(true));

// The server has the final say on what is valid, so nothing bad reaches the display.
$("applyJson").addEventListener("click", async () => {
  try {
    const applied = await writeLayout("/api/layout", JSON.stringify(JSON.parse($("json").value)));
    remember();
    layout = applied;
    if (!selected()) selectedId = null;
    jsonDirty = false;
    renderAll();
    refreshFrame();
    toast("JSON applied");
  } catch (error) {
    if (error.status === 409) await pullLayout(); else $("jsonError").textContent = error.message;
  }
});

// Pixel perfect: every DS pixel covers the same whole number of device pixels, so it stays sharp
// and even. Fill: as big as fits. The preview fits the whole shell, the editor just the screens.
let SHELL_W = 552, SHELL_H = 575;
const MARGIN = 16, DONE_ROOM = 90;

function fitPreview() {
  const shell = document.querySelector(".console"), main = document.querySelector("main"), stage = document.querySelector(".stage");
  const style = getComputedStyle(main);
  const width = main.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const bar = document.querySelector(".topbar").offsetHeight;
  document.documentElement.style.setProperty("--bar", `${bar}px`);
  const dock = document.querySelector(".dock");
  const tools = dock.offsetHeight + parseFloat(getComputedStyle(dock).marginTop);
  const room = window.innerHeight - bar - tools - MARGIN * 2;
  const ratio = window.devicePixelRatio || 1;
  // The preview is sized for the largest shell, so switching shells never changes the scale.
  const needW = editing ? BARE.width + DONE_ROOM * 2 : Math.max(...Object.values(SHELLS).map(shell => shell.width));
  const needH = editing ? BARE.height + MARGIN : Math.max(...Object.values(SHELLS).map(shell => shell.height));
  const fit = Math.min(width / needW, room / needH);
  // At least one CSS pixel per DS pixel, or two in the editor.
  const least = Math.max(1, Math.round((editing ? 2 : 1) * ratio));
  const scale = fill ? fit : Math.max(least, Math.floor(fit * ratio)) / ratio;
  shell.style.width = `${SHELL_W * scale}px`;

  // Centred in the room below the top bar, with the tools under it, on whole device pixels.
  const height = SHELL_H * scale + tools;
  const pad = Math.max(MARGIN, (window.innerHeight - bar - height) / 2);
  stage.style.paddingTop = `${pad}px`;
  shell.style.transform = "";
  const { left, top } = shell.getBoundingClientRect();
  const snap = value => Math.round(value * ratio) / ratio - value;
  // A fractional translate can paint a row off, so the top moves by its padding.
  stage.style.paddingTop = `${pad + snap(top)}px`;
  shell.style.transform = `translateX(${snap(left)}px)`;

  // The page's grid is anchored to the tools, which sit 2px in from their grid lines.
  const firstTool = document.querySelector(".tile").getBoundingClientRect();
  document.documentElement.style.setProperty("--grid-x", `${firstTool.left + window.scrollX - 2}px`);
  document.documentElement.style.setProperty("--grid-y", `${firstTool.top + window.scrollY - 2}px`);
  placeInspector();
}

function showScreens() {
  const bar = document.querySelector(".topbar").offsetHeight;
  const room = window.innerHeight - bar;
  const needed = screens.getBoundingClientRect().height;
  window.scrollBy(0, screens.getBoundingClientRect().top - bar - Math.max(0, (room - needed) / 2));
}

// Measured in DS pixels from each shell's SVG. x and y are where its top screen sits.
const SHELLS = {
  lite: { file: "/web/shell.svg", width: 552, height: 575, x: 148, y: 42, hinge: 101, radius: "0" },
  dsi: { file: "/web/shell-dsi.svg", width: 531, height: 544, x: 138, y: 34, hinge: 92, radius: "0" },
};

// The editor: no shell, just the two screens with a small gap.
const BARE = { width: W, height: H + 8, x: 0, y: 0, hinge: 8, radius: "0" };
let shellModel = "lite", editing = false, fill = false;

async function setShellModel(name) {
  shellModel = name;
  for (const button of $("shellModels").children) button.setAttribute("aria-pressed", String(button.dataset.model === name));
  try { localStorage.setItem("shellModel", name); } catch {}
  await applyShell();
}

function setEditing(on) {
  if (on === editing) return;
  editing = on;
  if (!on) select(null);
  document.documentElement.classList.toggle("editing", on);
  applyShell();
}

function setFill(on) {
  fill = on;
  $("fitButton").setAttribute("aria-pressed", String(on));
  $("fitButton").textContent = on ? "Fill" : "Pixel perfect";
  try { localStorage.setItem("fill", on ? "1" : "0"); } catch {}
  fitPreview();
}

async function applyShell() {
  const shell = editing ? BARE : SHELLS[shellModel];
  const root = document.documentElement.style;
  SHELL_W = shell.width;
  SHELL_H = shell.height;
  HINGE = shell.hinge;
  VIEW_H = H + HINGE;
  root.setProperty("--shell-ratio", `${shell.width} / ${shell.height}`);
  root.setProperty("--lcd-left", `${shell.x / shell.width * 100}%`);
  root.setProperty("--lcd-top", `${shell.y / shell.height * 100}%`);
  root.setProperty("--lcd-width", `${W / shell.width * 100}%`);
  root.setProperty("--hinge", shell.hinge);
  root.setProperty("--lcd-radius", shell.radius);
  fitPreview();
  showScreens();
  renderOverlay();
  renderAnimations();
  if (editing) return;
  const response = await fetch(shell.file);
  if (!editing && shell === SHELLS[shellModel]) $("shellArt").innerHTML = await response.text();
}

for (const button of $("shellModels").children) {
  button.addEventListener("click", () => { play("select"); setShellModel(button.dataset.model); });
}

let savedModel = null;
try { savedModel = localStorage.getItem("shellModel"); fill = localStorage.getItem("fill") === "1"; localStorage.removeItem("screensOnly"); } catch {}
setFill(fill);
setShellModel(SHELLS[savedModel] ? savedModel : "lite");
$("fitButton").addEventListener("click", () => { play("select"); setFill(!fill); });
$("doneButton").addEventListener("click", () => { play("back"); setEditing(false); });
screens.addEventListener("pointerdown", event => {
  if (editing) return;
  event.stopPropagation();
  play("launch");
  setEditing(true);
});
window.addEventListener("resize", fitPreview);
new ResizeObserver(fitPreview).observe($("drawer"));

const SHELL_COLOURS = {
  Black: "#3d3d3d", White: "#e4e4e6", Silver: "#a9adb3", Red: "#b3202a",
  Pink: "#e58fb0", Blue: "#23549e", Teal: "#1f8a8a", Gold: "#c29a3f",
};

// The cursor is the shell's colour too. In its art, grey 128 is the main shade.
const STYLUS_TIP = "0 63";
const stylusArt = new Image();
stylusArt.onload = () => tintStylus($("shellColour").value);
stylusArt.src = "/art/ui/stylus.png";

function stylusImage(shade, brightness, size) {
  const canvas = document.createElement("canvas");
  canvas.width = stylusArt.naturalWidth;
  canvas.height = stylusArt.naturalHeight;
  const context = canvas.getContext("2d");
  context.imageSmoothingEnabled = false;
  // Anchored at the tip, in the bottom left corner.
  context.drawImage(stylusArt, 0, canvas.height * (1 - size), canvas.width * size, canvas.height * size);
  const image = context.getImageData(0, 0, canvas.width, canvas.height);
  for (let i = 0; i < image.data.length; i += 4) {
    const grey = image.data[i];
    for (let c = 0; c < 3; c++) image.data[i + c] = Math.min(255, shade[c] * grey / 128 * brightness);
  }
  context.putImageData(image, 0, 0);
  return `url(${canvas.toDataURL()}) ${STYLUS_TIP}, auto`;
}

let stylusUp = null, stylusDown = null;

function tintStylus(colour) {
  if (!stylusArt.naturalWidth) return;
  const shade = [1, 3, 5].map(i => parseInt(colour.slice(i, i + 2), 16));
  stylusUp = stylusImage(shade, 1, 1);
  stylusDown = stylusImage(shade, 1.4, .875);
  document.documentElement.style.setProperty("--stylus", stylusUp);
}

// Cursors can't animate, so a press swaps the image and shows a ring at the tip.
window.addEventListener("pointerdown", event => {
  if (stylusDown) document.documentElement.style.setProperty("--stylus", stylusDown);
  if (!calm) Effects.tap(event.clientX, event.clientY, $("shellColour").value);
}, true);

let pressedControl = null;

function releaseStylus() {
  if (stylusUp) document.documentElement.style.setProperty("--stylus", stylusUp);
  Effects.release(pressedControl);
  pressedControl = null;
}
window.addEventListener("pointerup", releaseStylus);
window.addEventListener("pointercancel", releaseStylus);

document.querySelector(".console").addEventListener("pointerdown", event => {
  const control = event.target.closest(".press");
  if (!control) return;
  event.preventDefault();
  play(control.dataset.sound || "select");
  Effects.press(control, event);
  pressedControl = control;
});

function setShellColour(colour) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(colour.slice(i, i + 2), 16));
  const pale = (r * .299 + g * .587 + b * .114) / 255 > .6;
  const root = document.documentElement.style;
  root.setProperty("--ds-color", colour);
  root.setProperty("--ds-label", pale ? "#3d3d3d" : "#e8e8e8");
  $("shellColour").value = colour;
  tintStylus(colour);
  for (const swatch of $("swatches").children) swatch.setAttribute("aria-pressed", String(swatch.dataset.colour === colour));
  try { localStorage.setItem("shellColour", colour); } catch {}
}

$("swatches").append(...Object.entries(SHELL_COLOURS).map(([name, colour]) => {
  const swatch = document.createElement("button");
  swatch.className = "shell-swatch";
  swatch.title = name;
  swatch.setAttribute("aria-label", name);
  swatch.dataset.colour = colour;
  swatch.style.background = colour;
  swatch.addEventListener("click", () => { play("select"); setShellColour(colour); });
  return swatch;
}));
$("shellColour").addEventListener("input", () => setShellColour($("shellColour").value));
$("shellButton").addEventListener("click", () => { play("select"); toggleMenu($("shellMenu"), $("shellButton"), $("shellTail"), "bottom"); });

let savedShell = null;
try { savedShell = localStorage.getItem("shellColour"); } catch {}
setShellColour(/^#[0-9a-f]{6}$/i.test(savedShell) ? savedShell : SHELL_COLOURS.Black);
setTheme(document.documentElement.dataset.theme || "light");

// DS themes. Edits show on the DS straight away, and only stick when saved.

let dsThemes = null, dsTheme = null, dsThemeTimer = null;

async function changeDsTheme(request) {
  if (request.action === "preview" || request.action === "sleep") {
    dsThemes = await api("/api/themes", { method: "POST", body: JSON.stringify(request) });
    refreshFrame();
    return;
  }
  // Each theme has its own layout: save this one's last edit, then load the next one's.
  pulling = true;     // Keeps the status poll from pulling it halfway
  try {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; await save(); }
    await lastWrite;
    dsThemes = await api("/api/themes", { method: "POST", body: JSON.stringify(request) });
    const latest = await send("/api/layout");
    layout = latest.body;
    revision = latest.revision;
    unsaved = false;
    undoStack = [];
    redoStack = [];
    selectedId = null;
    updateHistoryButtons();
    renderAll();
    refreshFrame();
  } finally {
    pulling = false;
  }
}

function showDsTheme(name) {
  dsTheme = { ...dsThemes.themes[name] };
  $("dsThemeSelect").replaceChildren(...Object.keys(dsThemes.themes).map(key => new Option(key, key, false, key === name)));
  $("dsThemePaper").value = dsTheme.paper;
  $("dsThemeInk").value = dsTheme.ink;
  $("dsThemeBoost").value = dsTheme.boost;
  $("dsThemeBoostValue").textContent = `${dsTheme.boost}%`;
  $("dsThemeLift").value = dsTheme.lift;
  $("dsThemeLiftValue").textContent = `${dsTheme.lift}%`;
  $("dsThemeName").value = dsThemes.builtIn.includes(name) ? "" : name;
  const builtIn = dsThemes.builtIn.includes(name);
  $("dsThemeDelete").disabled = builtIn && !dsThemes.edited.includes(name);
  $("dsThemeDelete").textContent = builtIn ? "Reset" : "Delete";
  const sleep = dsThemes.sleep;
  $("sleepFile").replaceChildren(new Option("Black screen", ""),
    ...dsThemes.gifs.map(file => new Option(file.split("/").pop().replace(/\.gif$/i, "").replaceAll("_", " "), file)));
  $("sleepFile").value = sleep.file;
  $("sleepScreen").value = sleep.screen;
  $("sleepScreen").disabled = !sleep.file;
  $("sleepBrightness").value = sleep.brightness;
  $("sleepBrightnessValue").textContent = `${sleep.brightness}%`;
  $("dsThemeBars").replaceChildren(...dsThemes.colours.map((colour, index) => {
    const swatch = document.createElement("button");
    swatch.className = "shell-swatch";
    swatch.style.background = colour;
    swatch.setAttribute("aria-label", `Bar colour ${index}`);
    swatch.setAttribute("aria-pressed", String(index === dsTheme.bar));
    swatch.addEventListener("click", () => {
      play("select");
      dsTheme.bar = index;
      for (const other of $("dsThemeBars").children) other.setAttribute("aria-pressed", String(other === swatch));
      previewDsTheme();
    });
    return swatch;
  }));
}

function previewDsTheme() {
  clearTimeout(dsThemeTimer);
  dsThemeTimer = setTimeout(() => changeDsTheme({ action: "preview", theme: dsTheme }).catch(error => toast(error.message, true)), SAVE_DELAY);
}

for (const [input, key] of [["dsThemePaper", "paper"], ["dsThemeInk", "ink"]]) {
  $(input).addEventListener("input", () => { dsTheme[key] = $(input).value; previewDsTheme(); });
}
$("dsThemeBoost").addEventListener("input", () => {
  dsTheme.boost = Number($("dsThemeBoost").value);
  $("dsThemeBoostValue").textContent = `${dsTheme.boost}%`;
  previewDsTheme();
});
$("dsThemeLift").addEventListener("input", () => {
  dsTheme.lift = Number($("dsThemeLift").value);
  $("dsThemeLiftValue").textContent = `${dsTheme.lift}%`;
  previewDsTheme();
});
// The sleep screen is saved as it changes, as part of the active theme.
let sleepTimer = null;
function changeSleep() {
  const sleep = { file: $("sleepFile").value, screen: $("sleepScreen").value, brightness: Number($("sleepBrightness").value) };
  $("sleepScreen").disabled = !sleep.file;
  $("sleepBrightnessValue").textContent = `${sleep.brightness}%`;
  clearTimeout(sleepTimer);
  sleepTimer = setTimeout(() => changeDsTheme({ action: "sleep", sleep }).catch(error => toast(error.message, true)), SAVE_DELAY);
}
for (const id of ["sleepFile", "sleepScreen"]) $(id).addEventListener("change", () => { play("select"); changeSleep(); });
$("sleepBrightness").addEventListener("input", changeSleep);

$("dsThemeSelect").addEventListener("change", async () => {
  play("select");
  await changeDsTheme({ action: "use", name: $("dsThemeSelect").value });
  showDsTheme(dsThemes.active);
});
$("dsThemeSave").addEventListener("click", async () => {
  try {
    await changeDsTheme({ action: "save", name: $("dsThemeName").value, theme: dsTheme });
    showDsTheme(dsThemes.active);
    toast("Theme saved");
  } catch (error) { toast(error.message, true); }
});
$("dsThemeDelete").addEventListener("click", async () => {
  const name = $("dsThemeSelect").value, builtIn = dsThemes.builtIn.includes(name);
  if (!await confirmDialog(builtIn ? `Put ${name} back as it came, losing your changes to it?` : `Delete ${name}, with its layout and images?`)) return;
  await changeDsTheme({ action: "delete", name });
  showDsTheme(dsThemes.active);
  toast(builtIn ? "Theme reset" : "Theme deleted");
});
$("dsThemeButton").addEventListener("click", async () => {
  play("select");
  dsThemes = await api("/api/themes");
  showDsTheme(dsThemes.active);
  toggleMenu($("dsThemeMenu"), $("dsThemeButton"), $("dsThemeTail"), "bottom");
});

// Live status

// One fetch per frame, shared by both screens. Only one runs at a time, and it gives
// up in the end, so a stuck request can't use up the browser's connections.
async function refreshFrame() {
  if (frameLoading) { frameWanted = true; return; }
  frameLoading = true;
  try {
    const response = await fetch("/api/frame.png", { cache: "no-store", signal: AbortSignal.timeout(REQUEST_TIMEOUT) });
    if (response.ok) {
      const url = URL.createObjectURL(await response.blob());
      document.querySelectorAll(".lcd-frame").forEach(frame => { frame.src = url; });
      if (frameUrl) URL.revokeObjectURL(frameUrl);
      frameUrl = url;
    }
  } catch {
    // The next poll tries again.
  } finally {
    frameLoading = false;
    if (frameWanted) { frameWanted = false; refreshFrame(); }
  }
}

async function refresh() {
  if (refreshing || document.hidden) return;
  refreshing = true;
  try {
    const s = await api("/api/status", { signal: AbortSignal.timeout(REQUEST_TIMEOUT) });
    $("dot").classList.toggle("on", s.connected);
    $("link").textContent = s.connected ? `Connected on ${s.port}` : "Waiting for the DS…";
    $("version").textContent = s.version ? `v${s.version}` : "";
    $("cpu").textContent = `${s.cpu.toFixed(0)}%`;
    $("ram").textContent = `${s.ram.toFixed(0)}%`;
    $("cpuBar").style.width = `${s.cpu}%`;
    $("ramBar").style.width = `${s.ram}%`;
    $("sent").textContent = `${(s.bytesSent / 1024).toFixed(0)} KB`;
    if (!brightnessReady) {
      $("brightness").value = s.brightness;
      $("brightnessValue").textContent = `${s.brightness}%`;
      brightnessReady = true;
    }
    refreshFrame();
    if (s.layoutRevision > revision && !saveTimer && !saveAgain && !writing) pullLayout();
  } catch {
    $("dot").classList.remove("on");
    $("link").textContent = "App not running";
  } finally {
    refreshing = false;
  }
}

async function start() {
  [catalog, { body: layout, revision }] = await Promise.all([api("/api/catalog"), send("/api/layout")]);
  for (const [type, schema] of Object.entries(catalog.schema)) {
    const button = document.createElement("button");
    button.className = "ds-button";
    button.textContent = schema.label;
    button.dataset.type = type;
    button.addEventListener("click", () => { closeMenu(); addElement(type); });
    $("addGrid").append(button);
  }
  try {
    setSound(localStorage.getItem("sound") !== "0");
    const drawer = localStorage.getItem("drawer");
    if (drawer) { Effects.setSound(false); showDrawer(drawer); Effects.setSound(soundOn); }
  } catch {}
  renderAll();
  refresh();
  setInterval(refresh, 1000);
  document.addEventListener("visibilitychange", refresh);
}
start();
