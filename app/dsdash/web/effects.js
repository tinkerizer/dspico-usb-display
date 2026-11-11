// Feedback for presses: sound, the pressed look of shell buttons, and a ring where the stylus taps.
// Nothing here animates CSS or adds elements, so a press never changes Chrome's compositor layers.
const Effects = (() => {
  const VOLUME = 0.35, RING_MS = 280, RING_STEPS = 4;
  let audio = null, buffers = {}, soundOn = true;

  // Loaded and decoded with the page, so the first press doesn't wait for them. Browsers keep sound
  // off until the page is used, so it's switched on as a press starts, ahead of the click.
  try {
    audio = new AudioContext({ latencyHint: "interactive" });
    for (const sound of ["select", "back", "launch"]) {
      fetch(`/web/ui/sound/${sound}.wav`).then(r => r.arrayBuffer()).then(data => audio.decodeAudioData(data))
        .then(buffer => { buffers[sound] = buffer; }).catch(() => {});
    }
  } catch {}
  const wake = () => { if (audio && soundOn && audio.state === "suspended") audio.resume().catch(() => {}); };
  addEventListener("pointerdown", wake, true);
  addEventListener("keydown", wake, true);

  function play(name) {
    if (!soundOn || !audio || !buffers[name]) return;
    wake();
    const source = audio.createBufferSource(), gain = audio.createGain();
    gain.gain.value = VOLUME;
    source.buffer = buffers[name];
    source.connect(gain).connect(audio.destination);
    source.start();
  }

  // One canvas over the whole window, there from the start, so drawing rings never adds a layer.
  const canvas = document.createElement("canvas");
  canvas.className = "effects";
  document.body.append(canvas);
  const context = canvas.getContext("2d");
  let rings = [], drawing = false;

  function size() {
    const ratio = devicePixelRatio || 1;
    canvas.width = Math.round(innerWidth * ratio);
    canvas.height = Math.round(innerHeight * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }
  addEventListener("resize", size);
  size();

  function draw(now) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    rings = rings.filter(ring => now - ring.start < RING_MS);
    for (const ring of rings) {
      const step = Math.floor((now - ring.start) / RING_MS * RING_STEPS) / RING_STEPS;
      const half = 4 + step * 9;
      context.globalAlpha = 1 - step;
      context.lineWidth = 3;
      context.strokeStyle = "rgba(255, 255, 255, .7)";
      context.strokeRect(ring.x - half - 1, ring.y - half - 1, half * 2 + 2, half * 2 + 2);
      context.lineWidth = 2;
      context.strokeStyle = ring.colour;
      context.strokeRect(ring.x - half, ring.y - half, half * 2, half * 2);
    }
    context.globalAlpha = 1;
    drawing = rings.length > 0;
    if (drawing) requestAnimationFrame(draw);
  }

  function tap(x, y, colour) {
    rings.push({ x, y, colour, start: performance.now() });
    if (!drawing) { drawing = true; requestAnimationFrame(draw); }
  }

  // The pressed look is plain CSS on .down, with no transition, so it can't start an animation.
  function press(control, event) {
    if (control.dataset.dpad) {
      const box = control.getBoundingClientRect();
      const x = event.clientX - box.left - box.width / 2, y = event.clientY - box.top - box.height / 2;
      const across = Math.abs(x) > Math.abs(y);
      control.style.setProperty("--press-x", across ? `${Math.sign(x) * 1.2}px` : "0px");
      control.style.setProperty("--press-y", across ? "0px" : `${Math.sign(y) * 1.2}px`);
    }
    control.classList.add("down");
  }

  return {
    play, tap, press,
    release: control => control && control.classList.remove("down"),
    setSound: on => { soundOn = on; },
  };
})();
