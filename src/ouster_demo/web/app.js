import * as THREE from "three";
import { OrbitControls } from "/vendor/OrbitControls.js";

/* ------------------------------------------------------------------ constants */
const COLORS = {
  vehicle: "#40b4de", car: "#40b4de", truck: "#40b4de",
  pedestrian: "#f5811f", cyclist: "#f5c04a",
  structure: "#5b6b80", pole: "#5b6b80", debris: "#9aa6b4", unknown: "#9aa6b4",
};
const NO_LABEL = new Set(["structure", "pole"]);
const HIDE_IN_LIST = new Set(["structure", "pole", "debris"]);
const MAX_POINTS = 200000;

const $ = (id) => document.getElementById(id);
const el = {
  canvas: $("view"), labels: $("labels"), pill: $("statusPill"), pillText: $("statusText"),
  overlay: $("overlay"), ovTitle: $("ovTitle"), ovMsg: $("ovMsg"), ovHint: $("ovHint"), card: document.querySelector(".card"),
  objList: $("objList"), objCount: $("objCount"),
  fps: $("mFps"), pts: $("mPts"), obj: $("mObj"), lat: $("mLat"), total: $("mTotal"), bar: $("stageBar"),
  sensor: $("mSensor"), sensorSub: $("mSensorSub"),
};

/* ------------------------------------------------------------------ three.js scene */
const renderer = new THREE.WebGLRenderer({ canvas: el.canvas, antialias: true, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 600);
camera.position.set(-9, 7, 0);
const controls = new OrbitControls(camera, el.canvas);
controls.target.set(2, 0, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI * 0.495;
controls.autoRotateSpeed = 0.8;

// Sensor frame (x fwd, y left, z up)  ->  three.js (x, z, -y): a proper rotation, Y up.
const S2T = (x, y, z) => new THREE.Vector3(x, z, -y);

/* points ------------------------------------------------------------------- */
const geom = new THREE.BufferGeometry();
const posArr = new Float32Array(MAX_POINTS * 3);
const reflArr = new Float32Array(MAX_POINTS);
const tagArr = new Float32Array(MAX_POINTS);
geom.setAttribute("position", new THREE.BufferAttribute(posArr, 3).setUsage(THREE.DynamicDrawUsage));
geom.setAttribute("aRefl", new THREE.BufferAttribute(reflArr, 1).setUsage(THREE.DynamicDrawUsage));
geom.setAttribute("aTag", new THREE.BufferAttribute(tagArr, 1).setUsage(THREE.DynamicDrawUsage));
geom.setDrawRange(0, 0);

const pointMat = new THREE.ShaderMaterial({
  uniforms: {
    uSize: { value: 3.0 }, uMode: { value: 2 }, uShowGround: { value: 1 },
    uPx: { value: renderer.getPixelRatio() }, uGroundY: { value: -1.8 },
  },
  vertexShader: /* glsl */ `
    attribute float aRefl; attribute float aTag;
    uniform float uSize, uMode, uShowGround, uPx, uGroundY;
    varying vec3 vColor; varying float vA;
    vec3 ramp(float t) {
      vec3 c0 = vec3(0.09, 0.19, 0.33), c1 = vec3(0.25, 0.71, 0.87), c2 = vec3(0.95, 0.96, 0.97), c3 = vec3(0.96, 0.51, 0.12);
      t = clamp(t, 0., 1.);
      if (t < .4) return mix(c0, c1, t / .4);
      if (t < .75) return mix(c1, c2, (t - .4) / .35);
      return mix(c2, c3, (t - .75) / .25);
    }
    vec3 classColor(float tag) {
      if (tag < .5) return vec3(0.28, 0.33, 0.40);          // none
      if (tag < 1.5) return vec3(0.14, 0.20, 0.27);         // ground
      if (tag < 2.5) return vec3(0.36, 0.42, 0.50);         // structure
      if (tag < 3.5) return vec3(0.25, 0.71, 0.87);         // vehicle
      if (tag < 4.5) return vec3(0.96, 0.51, 0.12);         // pedestrian
      if (tag < 5.5) return vec3(0.96, 0.75, 0.29);         // cyclist
      return vec3(0.60, 0.65, 0.71);                        // other obstacle
    }
    void main() {
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      gl_Position = projectionMatrix * mv;
      float rng = length(position.xz);
      if (uMode < .5)       vColor = ramp((position.y - uGroundY) / 4.5);
      else if (uMode < 1.5) vColor = mix(vec3(0.12, 0.18, 0.27), vec3(1.0, 0.86, 0.68), clamp(aRefl / 140., 0., 1.));
      else if (uMode < 2.5) vColor = classColor(aTag);
      else                  vColor = ramp(rng / 50.);
      vA = 1.0;
      if (aTag > .5 && aTag < 1.5) {
        if (uShowGround < .5) gl_Position = vec4(2., 2., 2., 1.);
        if (uMode > 1.5 && uMode < 2.5) vA = .75;
      }
      gl_PointSize = clamp(uSize * uPx * (24.0 / -mv.z), 1.5 * uPx, 9.0 * uPx);
    }`,
  fragmentShader: /* glsl */ `
    varying vec3 vColor; varying float vA;
    void main() {
      vec2 c = gl_PointCoord - .5;
      if (dot(c, c) > .25) discard;
      gl_FragColor = vec4(vColor * vA, 1.0);
    }`,
});
const points = new THREE.Points(geom, pointMat);
points.frustumCulled = false;
scene.add(points);

/* range rings + ground ------------------------------------------------------ */
const rings = new THREE.Group();
scene.add(rings);
(function buildRings() {
  const mat = (a) => new THREE.LineBasicMaterial({ color: 0xf5811f, transparent: true, opacity: a });
  for (const r of [2, 5, 10, 20, 40]) {
    const pts = [];
    for (let i = 0; i <= 128; i++) pts.push(new THREE.Vector3(Math.cos((i / 128) * 2 * Math.PI) * r, 0, Math.sin((i / 128) * 2 * Math.PI) * r));
    rings.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat(r === 5 ? 0.38 : 0.2)));
  }
  const axis = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-42, 0, 0), new THREE.Vector3(42, 0, 0), new THREE.Vector3(0, 0, -42), new THREE.Vector3(0, 0, 42),
  ]);
  rings.add(new THREE.LineSegments(axis, mat(0.12)));
  // forward marker (sensor +X)
  const tri = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(1.0, 0, 0), new THREE.Vector3(0.5, 0, 0.3), new THREE.Vector3(0.5, 0, -0.3), new THREE.Vector3(1.0, 0, 0)]);
  rings.add(new THREE.Line(tri, new THREE.LineBasicMaterial({ color: 0xf5811f })));
})();

/* sensor glyph */
const sensorGlyph = new THREE.Mesh(
  new THREE.CylinderGeometry(0.06, 0.06, 0.09, 24),
  new THREE.MeshBasicMaterial({ color: 0xf5811f }),
);
scene.add(sensorGlyph);

/* boxes / trails / arrows ------------------------------------------------------- */
const unitBox = new THREE.BoxGeometry(1, 1, 1);
const unitEdges = new THREE.EdgesGeometry(unitBox);
const tracks = new Map(); // id -> entry
let groundZ = -1.8;

function makeEntry(t) {
  const color = new THREE.Color(COLORS[t.cls] || "#9aa6b4");
  const group = new THREE.Group();
  const edges = new THREE.LineSegments(unitEdges, new THREE.LineBasicMaterial({ color }));
  const fill = new THREE.Mesh(unitBox, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.07, depthWrite: false }));
  group.add(edges, fill);
  scene.add(group);

  const trailGeom = new THREE.BufferGeometry();
  trailGeom.setAttribute("position", new THREE.BufferAttribute(new Float32Array(60 * 3), 3));
  const trail = new THREE.Line(trailGeom, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.7 }));
  trail.frustumCulled = false;
  scene.add(trail);

  const arrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 1, color, 0.5, 0.35);
  scene.add(arrow);

  const label = document.createElement("div");
  label.className = "tag";
  label.style.setProperty("--c", "#" + color.getHexString());
  el.labels.appendChild(label);
  return { group, edges, fill, trail, trailGeom, arrow, label, cls: t.cls, text: "" };
}

function disposeEntry(e) {
  scene.remove(e.group, e.trail, e.arrow);
  e.edges.material.dispose(); e.fill.material.dispose(); e.trail.material.dispose(); e.trailGeom.dispose();
  e.label.remove();
}

const ui = { boxes: true, trails: true, spin: false };

function updateTracks(list) {
  const seen = new Set();
  for (const t of list) {
    seen.add(t.id);
    let e = tracks.get(t.id);
    if (!e) { e = makeEntry(t); tracks.set(t.id, e); }
    if (e.cls !== t.cls) {
      e.cls = t.cls;
      const c = new THREE.Color(COLORS[t.cls] || "#9aa6b4");
      e.edges.material.color.copy(c); e.fill.material.color.copy(c); e.trail.material.color.copy(c); e.arrow.setColor(c);
      e.label.style.setProperty("--c", "#" + c.getHexString());
    }
    const [cx, cy, cz] = t.c;
    const [l, w, h] = t.s;
    const faint = NO_LABEL.has(t.cls);
    e.group.visible = ui.boxes && !faint;   // walls/poles: points only, no wireframe clutter
    e.group.position.set(cx, cz, -cy);
    e.group.rotation.set(0, t.yaw, 0);
    e.group.scale.set(l, h, w);
    e.edges.material.opacity = faint ? 0.45 : 1; e.edges.material.transparent = faint;
    e.fill.visible = !faint;

    // trail
    const tr = t.trail;
    const attr = e.trailGeom.attributes.position;
    const n = Math.min(tr.length, 60);
    for (let i = 0; i < n; i++) attr.setXYZ(i, tr[i][0], groundZ + 0.06, -tr[i][1]);
    attr.needsUpdate = true;
    e.trailGeom.setDrawRange(0, n);
    e.trail.visible = ui.trails && t.moving && !faint;

    // velocity arrow
    e.arrow.visible = ui.boxes && t.moving && !faint;
    if (e.arrow.visible) {
      const dir = new THREE.Vector3(t.v[0], 0, -t.v[1]).normalize();
      e.arrow.position.set(cx, groundZ + 0.12, -cy);
      e.arrow.setDirection(dir);
      e.arrow.setLength(Math.min(1 + t.speed * 0.7, 7), 0.6, 0.4);
    }

    // label text
    if (faint || !ui.boxes) { e.label.style.display = "none"; }
    else {
      const kmh = t.speed * 3.6;
      const txt = `${t.cls.toUpperCase()} #${t.id}`;
      const sub = t.moving ? `${kmh.toFixed(0)} km/h` : "static";
      const full = txt + "|" + sub;
      if (full !== e.text) { e.label.innerHTML = `${txt}<small>${sub}</small>`; e.text = full; }
      e.label.style.display = "";
    }
    e.anchor = new THREE.Vector3(cx, cz + h / 2 + 0.25, -cy);
  }
  for (const [id, e] of tracks) if (!seen.has(id)) { disposeEntry(e); tracks.delete(id); }
}

function projectLabels() {
  const w = el.canvas.clientWidth, h = el.canvas.clientHeight;
  const v = new THREE.Vector3();
  for (const e of tracks.values()) {
    if (!e.anchor || e.label.style.display === "none") continue;
    v.copy(e.anchor).project(camera);
    if (v.z > 1 || v.z < -1) { e.label.style.visibility = "hidden"; continue; }
    e.label.style.visibility = "visible";
    e.label.style.transform = `translate3d(${((v.x * 0.5 + 0.5) * w).toFixed(1)}px, ${((-v.y * 0.5 + 0.5) * h).toFixed(1)}px, 0) translate(-50%, -100%)`;
  }
}

/* ------------------------------------------------------------------ resize + render loop */
function resize() {
  const w = el.canvas.clientWidth, h = el.canvas.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

renderer.setAnimationLoop(() => {
  controls.autoRotate = ui.spin;
  controls.update();
  renderer.render(scene, camera);
  projectLabels();
});

/* ------------------------------------------------------------------ frame decoding */
const decoder = new TextDecoder();
let lastFrameAt = 0;
let lastListAt = 0;
let sensorKey = "";

function onFrame(buf) {
  const dv = new DataView(buf);
  const hlen = dv.getUint32(0, true);
  const hdr = JSON.parse(decoder.decode(new Uint8Array(buf, 4, hlen)));
  const n = Math.min(hdr.n, MAX_POINTS);
  const off = 4 + hlen;
  const xyz = new Int16Array(buf, off, hdr.n * 3);
  const refl = new Uint8Array(buf, off + hdr.n * 6, hdr.n);
  const tag = new Uint8Array(buf, off + hdr.n * 7, hdr.n);
  for (let i = 0, j = 0; i < n; i++, j += 3) {
    // sensor (x, y, z) cm  ->  three (x, z, -y) m
    posArr[j] = xyz[j] * 0.01;
    posArr[j + 1] = xyz[j + 2] * 0.01;
    posArr[j + 2] = -xyz[j + 1] * 0.01;
    reflArr[i] = refl[i];
    tagArr[i] = tag[i];
  }
  geom.attributes.position.needsUpdate = true;
  geom.attributes.aRefl.needsUpdate = true;
  geom.attributes.aTag.needsUpdate = true;
  geom.setDrawRange(0, n);

  groundZ = hdr.ground.z;
  pointMat.uniforms.uGroundY.value = groundZ;
  rings.position.y = groundZ + 0.02;

  updateTracks(hdr.tracks);
  lastFrameAt = performance.now();
  hideOverlay();

  // HUD
  const shown = hdr.tracks.filter((t) => !HIDE_IN_LIST.has(t.cls));
  el.fps.textContent = hdr.fps ? hdr.fps.toFixed(1) : "–";
  el.pts.textContent = hdr.n >= 1000 ? (hdr.n / 1000).toFixed(1) + "k" : hdr.n;
  el.obj.textContent = shown.length;
  el.lat.textContent = hdr.latency_ms.toFixed(0) + " ms";
  const tm = hdr.timings, tot = tm.total || 1;
  el.total.textContent = tm.total.toFixed(1) + " ms";
  el.bar.innerHTML = ["ground", "cluster", "boxes", "track"]
    .map((k, i) => `<div class="s${i + 1}" style="width:${((tm[k] / tot) * 100).toFixed(1)}%" title="${k} ${tm[k].toFixed(1)} ms"></div>`).join("");
  const s = hdr.sensor || {};
  const key = JSON.stringify(s);
  if (key !== sensorKey) {
    sensorKey = key;
    el.sensor.textContent = s.model || "–";
    el.sensorSub.textContent = [s.rows && `${s.rows}×${s.cols}`, s.lidar_mode, s.firmware && "FW " + s.firmware].filter(Boolean).join(" · ");
    sensorGlyph.position.set(0, 0, 0);
  }
  const now = performance.now();
  if (now - lastListAt > 250) { lastListAt = now; renderList(shown); el.objCount.textContent = shown.length; }
}

function renderList(list) {
  if (!list.length) { el.objList.innerHTML = `<div class="empty">No moving or static objects in range.</div>`; return; }
  const rows = [...list].sort((a, b) => Math.hypot(a.c[0], a.c[1]) - Math.hypot(b.c[0], b.c[1])).slice(0, 40);
  el.objList.innerHTML = rows.map((t) => {
    const d = Math.hypot(t.c[0], t.c[1]);
    const c = COLORS[t.cls] || "#9aa6b4";
    return `<div class="obj" style="--c:${c}">
      <span class="id">#${t.id}</span>
      <div><div class="cls"><i></i>${t.cls[0].toUpperCase() + t.cls.slice(1)}</div>
        <div class="sub">${t.s[0].toFixed(1)}×${t.s[1].toFixed(1)}×${t.s[2].toFixed(1)} m</div></div>
      <div class="spd">${d.toFixed(1)} m<small>${t.moving ? (t.speed * 3.6).toFixed(0) + " km/h" : "static"}</small></div>
    </div>`;
  }).join("");
}

/* ------------------------------------------------------------------ status + overlay */
let state = "connecting";
let currentSource = "";

function setPill(s, text) { el.pill.dataset.state = s; el.pillText.textContent = text; }

function showOverlay(title, msg, hint = "", error = false) {
  el.card.classList.toggle("err", error);
  el.ovTitle.textContent = title; el.ovMsg.textContent = msg; el.ovHint.textContent = hint;
  el.overlay.hidden = false;
}
function hideOverlay() { el.overlay.hidden = true; }

function errorHints(msg) {
  const host = currentSource || "<sensor-ip>";
  const lines = [];
  if (/Could not connect|CurlClient|timed? ?out|resolve/i.test(msg))
    lines.push("• Sensor HTTP API unreachable: check cable/power, IP and subnet.", "• .local names do not resolve in Docker - use the sensor IP.");
  if (/firmware|version/i.test(msg)) lines.push("• SDK / firmware mismatch - see docs/LAB_DEBUG.md.");
  if (/timeout|packets|ClientTimeout/i.test(msg)) lines.push("• No UDP data: firewall, or Docker not on host networking.");
  lines.push(`\nDiagnose:  ouster-demo doctor ${host} --sdk`);
  return lines.join("\n");
}

function onStatus(s) {
  state = s.state;
  currentSource = s.source || "";
  if (document.activeElement !== $("sourceInput") && !$("sourceInput").value) $("sourceInput").value = currentSource;
  if (s.state === "streaming") {
    setPill("streaming", s.source_kind === "file" ? "Replay" : "Live");
    if (!lastFrameAt) showOverlay("Waiting for first frame…", `Connected to ${currentSource}`);
  } else if (s.state === "idle") {
    setPill("offline", "No sensor");
    showOverlay("Connect your Ouster sensor", s.message,
      "Type the sensor IP or hostname in the Source box above and press Connect.\n\nNot sure of the IP?   ouster-demo discover");
    $("sourceInput").focus();
  } else if (s.state === "error") {
    setPill("error", "Error");
    showOverlay("Cannot read lidar stream", s.message, errorHints(s.message), true);
  } else {
    setPill("connecting", "Connecting");
    showOverlay("Connecting…", s.message || `Opening ${currentSource}`);
  }
}

setInterval(() => {   // stream stalled although the backend thinks it is streaming
  if (state === "streaming" && lastFrameAt && performance.now() - lastFrameAt > 4000) {
    setPill("connecting", "No data");
    showOverlay("No lidar frames arriving", `Source ${currentSource} is connected but produced no frames for 4 s.`,
      "• Sensor sending to the wrong IP? (udp_dest)\n• Firewall dropping UDP 7502/7503\n• Docker must use host networking\n\n" +
      `Diagnose:  ouster-demo doctor ${currentSource} --sdk`, true);
  }
}, 1000);

/* ------------------------------------------------------------------ websocket */
let ws;
function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { lastFrameAt = 0; };
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") { const m = JSON.parse(ev.data); if (m.type === "status") onStatus(m); }
    else onFrame(ev.data);
  };
  ws.onclose = () => {
    state = "offline"; lastFrameAt = 0;
    setPill("offline", "Server offline");
    showOverlay("Server unreachable", "Reconnecting…", "Is `ouster-demo` still running?");
    setTimeout(connect, 1500);
  };
}
connect();

/* ------------------------------------------------------------------ controls */
const bind = (id, fn) => $(id).addEventListener("change", (e) => fn(e.target.checked));
bind("tGround", (v) => (pointMat.uniforms.uShowGround.value = v ? 1 : 0));
bind("tBoxes", (v) => { ui.boxes = v; });
bind("tTrails", (v) => { ui.trails = v; });
bind("tRings", (v) => { rings.visible = v; });
$("sSize").addEventListener("input", (e) => { pointMat.uniforms.uSize.value = +e.target.value; $("vSize").textContent = (+e.target.value).toFixed(1); });

document.querySelectorAll("#colorMode button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#colorMode button").forEach((x) => x.classList.toggle("on", x === b));
  pointMat.uniforms.uMode.value = +b.dataset.mode;
}));

function tween(pos, target) {
  const p0 = camera.position.clone(), t0 = controls.target.clone(), t = performance.now();
  const step = () => {
    const k = Math.min((performance.now() - t) / 600, 1), e = 1 - Math.pow(1 - k, 3);
    camera.position.lerpVectors(p0, pos, e); controls.target.lerpVectors(t0, target, e);
    if (k < 1) requestAnimationFrame(step);
  };
  step();
}
$("vChase").onclick = () => tween(new THREE.Vector3(-9, 7, 0), new THREE.Vector3(2, 0, 0));
$("vTop").onclick = () => tween(new THREE.Vector3(0.01, 22, 0), new THREE.Vector3(0, 0, 0));
$("vSpin").onclick = (e) => { ui.spin = !ui.spin; e.target.classList.toggle("on", ui.spin); };

/* perception sliders */
const fmt = { max_range_m: "vRange", max_height_m: "vHeight", ground_thresh_m: "vGround", cluster_eps_m: "vEps", min_cluster_points: "vMin" };
fetch("/api/params").then((r) => r.json()).then((p) => {
  document.querySelectorAll("input[data-key]").forEach((i) => { i.value = p[i.dataset.key]; $(fmt[i.dataset.key]).textContent = p[i.dataset.key]; });
}).catch(() => {});
document.querySelectorAll("input[data-key]").forEach((i) => {
  i.addEventListener("input", () => { $(fmt[i.dataset.key]).textContent = i.value; });
  i.addEventListener("change", () => fetch("/api/params", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [i.dataset.key]: +i.value }) }));
});

/* source switching */
const hist = JSON.parse(localStorage.getItem("sources") || "[]");
const dl = $("sourceOptions");
hist.forEach((h) => { const o = document.createElement("option"); o.value = h; dl.appendChild(o); });
fetch("/api/status").then((r) => r.json()).then((s) => { $("sourceInput").value = s.source || ""; }).catch(() => {});
$("sourceForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const source = $("sourceInput").value.trim();
  if (!source) return;
  if (!hist.includes(source)) { hist.unshift(source); localStorage.setItem("sources", JSON.stringify(hist.slice(0, 8))); }
  lastFrameAt = 0;
  showOverlay("Connecting…", `Opening ${source}`);
  await fetch("/api/source", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }) });
});
