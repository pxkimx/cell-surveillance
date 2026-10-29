"""The animated background: a simulated fluorescence field under surveillance.

It is a drawing, not data, but it is built the way a microscope image is built.
The cells are drawn as light on a small "camera" image, which is blurred by the
optics (an out-of-focus haze plus the limited sharpness of the lens), given the
noise of a camera, and only then enlarged to the screen. What the software
would add (outlines, tracks, labels) is drawn on top, sharp.

The cells behave like cells in a dish. Each one crawls by pushing out a
lamellipodium that sticks to the surface; the body follows, and the rear is
left behind as a tail that stretches and then snaps back. There are two
colours, as in a two-channel movie: a green NLS reporter and a red histone. A
nucleus grows a bleb and ruptures; the reporter floods the cell, leaving the
nucleus red, and is slowly re-imported.
A cell rounds up, its chromosomes line up and are pulled apart, and a furrow
pinches it in two. A dying cell shrinks, blebs and breaks up. Neurons extend
branching neurites led by growth cones.
"""


def background_html(animate: bool = True, close_url: str = "", theme: str = "dark") -> str:
    """The page. With animate=False it draws one picture and then does no further work.

    close_url is where the page reports that the app's window is being closed (see lifecycle.py).
    theme is "dark" (light on black, as on the microscope) or "light" (the same field, paler, on grey).
    """
    return (PAGE.replace("__STILL__", "false" if animate else "true").replace("__CLOSE_URL__", close_url)
            .replace("__THEME__", "light" if theme == "light" else "dark"))


PAGE = r"""
<!doctype html>
<html data-theme="__THEME__"><head><meta charset="utf-8">
<style>
  html, body { margin:0; height:100%; background:#020608; overflow:hidden;
               font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  canvas { position:fixed; inset:0; width:100%; height:100%; display:block; }
  .grid { position:fixed; inset:0; pointer-events:none;
          background: linear-gradient(rgba(131,207,210,.04) 1px, transparent 1px) 0 0 / 100% 48px,
                      linear-gradient(90deg, rgba(131,207,210,.04) 1px, transparent 1px) 0 0 / 48px 100%; }
  .vig { position:fixed; inset:0; pointer-events:none;
         background: radial-gradient(ellipse at 50% 45%, transparent 55%, rgba(0,0,0,.5) 100%); }
  .strip { position:fixed; left:22px; right:22px; bottom:13px; display:flex; align-items:flex-end; gap:18px; pointer-events:none; }
  .key { color:#a9c1c0; font-size:10px; letter-spacing:.08em; text-transform:uppercase; text-shadow:0 1px 6px #000; white-space:nowrap; flex:none; }
  .key span { margin-right:14px; white-space:nowrap; }
  .key .ch { color:#dbe9e6; } .key .ch i { border-radius:2px; }
  .key i { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; vertical-align:-1px; }
  .grow { flex:1; }
  .hud { flex:none; color:#cfe9e4; font-size:10.5px; letter-spacing:.07em; white-space:nowrap; padding:6px 12px 7px; border-radius:10px;
         border:1px solid rgba(131,207,210,.22); background:rgba(2,8,10,.6); }
  .hud b { color:#fff; font-weight:700; }
  .hud .rup b { color:#ff6f9f; } .hud .div b { color:#ffd60a; } .hud .dth b { color:#ff9d3c; } .hud .ax b { color:#d3b4ff; }
  .live { display:inline-block; width:7px; height:7px; border-radius:50%; background:#ff4081; margin-right:6px;
          animation: blink 1.4s ease-in-out infinite; }
  @keyframes blink { 0%,100% { opacity:1; } 50% { opacity:.2; } }
  .bar { color:#fff; font-size:10px; letter-spacing:.08em; text-align:center; text-shadow:0 1px 6px #000; }
  .bar i { display:block; width:96px; height:3px; background:#fff; margin-top:5px; border-radius:2px; }
  /* the light look: the same field drawn as pigment on pale grey instead of light on black */
  html[data-theme="light"], html[data-theme="light"] body { background:#f3f4f6; }
  html[data-theme="light"] .grid { background-image: linear-gradient(rgba(0,0,0,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,.05) 1px, transparent 1px); }
  html[data-theme="light"] .vig { background: radial-gradient(ellipse at 50% 45%, transparent 60%, rgba(0,0,0,.08) 100%); }
  html[data-theme="light"] .key { color:#4a555a; text-shadow:none; } html[data-theme="light"] .key .ch { color:#2d3639; }
  html[data-theme="light"] .hud { color:#2d3639; border-color:rgba(0,0,0,.14); background:rgba(255,255,255,.7); }
  html[data-theme="light"] .hud b { color:#111; }
  html[data-theme="light"] .hud .rup b { color:#c2185b; } html[data-theme="light"] .hud .div b { color:#9a6b00; }
  html[data-theme="light"] .hud .dth b { color:#b45309; } html[data-theme="light"] .hud .ax b { color:#6d28d9; }
  html[data-theme="light"] .bar { color:#222; text-shadow:none; } html[data-theme="light"] .bar i { background:#222; }
  @media (max-width: 1500px) { .key span:not(.ch) { display:none; } }
  @media (max-width: 1000px) { .key { display:none; } }
  @media (max-width: 760px) { .hud { display:none; } }
</style></head>
<body>
<canvas id="img"></canvas>
<div class="grid"></div>
<canvas id="c"></canvas>
<div class="vig"></div>
<div class="strip">
  <div class="key"><span class="ch"><i style="background:#3cf07a"></i>NLS reporter</span><span class="ch"><i style="background:#ff3450"></i>histone</span>
    <span><i style="background:#5ac8ff"></i>intact</span><span><i style="background:#ff4081"></i>rupture</span>
    <span><i style="background:#ffd60a"></i>division</span><span><i style="background:#ff9d3c"></i>death</span>
    <span><i style="background:#c59bff"></i>neurite growth</span></div>
  <div class="grow"></div>
  <div class="hud"><span class="live"></span><b>TRACKING</b> &nbsp; t = <b id="t">00:00</b> h &nbsp; cells <b id="n">0</b> &nbsp;
    <span class="rup">ruptures <b id="r">0</b></span> &nbsp; <span class="div">divisions <b id="d">0</b></span> &nbsp;
    <span class="dth">deaths <b id="x">0</b></span> &nbsp; <span class="ax">neurite <b id="a">0</b> &micro;m</span></div>
  <div class="bar">50 &micro;m<i></i></div>
</div>
<script>
// Tell the app when its window is closed, so that it quits instead of running on unseen.
(() => {
  const url = "__CLOSE_URL__", look = "__THEME__";
  try {
    const top = window.parent, root = top.document.documentElement;
    if (root.dataset.theme && root.dataset.theme !== look) top.location.reload();
    root.dataset.theme = look;
    if (url && !top.__cellSurveillanceClose) {
      top.__cellSurveillanceClose = true;
      top.addEventListener('pagehide', e => { if (!e.persisted) top.navigator.sendBeacon(url); });
    }
  } catch (e) {}
})();
(() => {
  const $ = id => document.getElementById(id);
  const c = $('c'), g = c.getContext('2d');
  const F = $('img'), gf = F.getContext('2d');                           // the camera image; the browser enlarges it
  const B = document.createElement('canvas'), gb = B.getContext('2d');   // light from out of the focal plane
  const BS = .25;
  const qs = new URLSearchParams(location.search || (window.frameElement && window.frameElement.getAttribute('data-q')) || ''), demo = qs.get('demo'), at = parseFloat(qs.get('at') || '0'), freeze = qs.has('freeze'), off = (qs.get('off') || '').split(',');
  const dpr = Math.min(window.devicePixelRatio || 1, parseFloat(qs.get('dpr') || '2'));
  const still = __STILL__ || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const light = '__THEME__' === 'light', ADD = light ? 'multiply' : 'lighter';   // on grey, fluorescence is drawn as pigment
  const INK = light ? { trail: '70,110,150', outline: '0,100,160', text: '255,255,255', textBg: '255,255,255', id: '40,50,56', corner: '40,50,56', rupt: '200,20,90', mito: '140,95,0', death: '180,70,0', arbor: '90,40,170' }
                    : { trail: '90,200,255', outline: '90,200,255', text: '', textBg: '2,8,10', id: '255,255,255', corner: '255,255,255', rupt: '255,130,170', mito: '255,224,80', death: '255,170,90', arbor: '215,190,255' };
  const R = (a, b) => a + Math.random() * (b - a), TAU = Math.PI * 2;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), lerp = (a, b, t) => a + (b - a) * t;
  const ease = t => { t = clamp(t, 0, 1); return t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; };
  const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const turn = (from, to) => Math.atan2(Math.sin(to - from), Math.cos(to - from));
  const turnAxis = (from, to) => { let d = turn(from, to); if (d > Math.PI / 2) d -= Math.PI; if (d < -Math.PI / 2) d += Math.PI; return d; };
  let W = 0, H = 0, FS = .7, ready = false, target = 8;
  function size() {
    W = c.clientWidth || window.innerWidth; H = c.clientHeight || window.innerHeight;
    c.width = Math.max(2, Math.round(W * dpr)); c.height = Math.max(2, Math.round(H * dpr));
    FS = clamp(Math.sqrt(560000 / Math.max(W * H, 1)), .5, .8);      // the camera has a fixed number of pixels
    F.width = Math.max(2, Math.ceil(W * FS)); F.height = Math.max(2, Math.ceil(H * FS));
    B.width = Math.max(2, Math.ceil(W * BS)); B.height = Math.max(2, Math.ceil(H * BS));
    target = clamp(Math.round(W * H / 62000), 4, 20);                 // about as crowded whatever the window
  }
  let force = false;                                                     // draw the next frame even while resting
  window.addEventListener('resize', () => { size(); force = true; if (ready && (still || freeze)) requestAnimationFrame(frame); });

  const MT = 9.5, DT = 8, RT = 9, CORE = .6, RED = '255,22,52', HIST = .7;                  // seconds a division, a death and a rupture take
  let nextId = 1, ruptures = 0, divisions = 0, deaths = 0, clock = 0, last = performance.now();
  const cells = [], neurons = [], ghosts = [], specks = [];

  // ------------------------------------------------------------------ textures, made once
  function tile(n, fn) {
    const cv = document.createElement('canvas'); cv.width = cv.height = n;
    const q = cv.getContext('2d'), im = q.createImageData(n, n); fn(im.data); q.putImageData(im, 0, 0); return cv;
  }
  const gauss = () => { let u = 0; for (let i = 0; i < 4; i++) u += Math.random(); return (u - 2) / .577; };
  // photon noise: grey around the middle, laid over the image so that it scales with the signal
  const shot = [0, 1, 2].map(() => gf.createPattern(tile(256, d => { for (let i = 0; i < d.length; i += 4) {
    d[i] = d[i + 1] = d[i + 2] = clamp(128 + gauss() * 44, 0, 255); d[i + 3] = 255; } }), 'repeat'));
  // camera noise: a faint speckle that is there even where nothing fluoresces
  const dark = [0, 1, 2].map(() => gf.createPattern(tile(256, d => { for (let i = 0; i < d.length; i += 4) {
    const v = Math.abs(gauss()); d[i] = 16 * Math.abs(gauss()); d[i + 1] = 24 * v; d[i + 2] = 18 * v; d[i + 3] = 255; } }), 'repeat'));
  function cloud(n, grid, fn) {                                          // soft blotches
    const cv = document.createElement('canvas'); cv.width = cv.height = n;
    const q = cv.getContext('2d'); q.imageSmoothingEnabled = true; q.imageSmoothingQuality = 'high';
    for (const [gr, a] of grid) { q.globalAlpha = a; q.drawImage(tile(gr, fn), 0, 0, n, n); }
    return cv;
  }
  // cytoplasm is granular: organelles leave darker holes in a soluble reporter
  const cyto = cloud(256, [[26, 1], [60, .6]], d => { for (let i = 0; i < d.length; i += 4) {
    const v = Math.random(); d[i] = 80; d[i + 1] = 255; d[i + 2] = 140; d[i + 3] = 255 * v * v; } });
  // the nucleus is not uniform either; this one is multiplied in, so white leaves the image alone
  const chrom = cloud(256, [[40, 1]], d => { for (let i = 0; i < d.length; i += 4) {
    const v = 165 + 90 * Math.random(); d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 255; } });

  // ------------------------------------------------------------------ cells
  function lobe(k, ang, kind, len = 0) {
    const d = k.rb * k.s * (CORE + len);
    return { x: k.x + Math.cos(ang) * d, y: k.y + Math.sin(ang) * d, ang, a: ang, kind, len,
             w: kind === 'lam' ? R(.62, .95) : R(.2, .34), reach: R(.75, 1.15), snap: R(1.0, 1.7), hold: R(5, 14), age: 0, ph: R(0, TAU) };
  }
  function cell(x, y, scale = 1, bare = false) {
    const k = { id: nextId++, x, y, s: scale, dir: R(0, TAU), sp: R(7, 13), fade: 0, rb: R(31, 38), ph: R(0, TAU),
                na: R(16, 20), nb: R(11.5, 14), nrot: R(0, TAU), nw: [R(0, TAU), R(0, TAU), R(.04, .08), R(.03, .06)],
                nucleoli: Array.from({ length: Math.random() < .5 ? 2 : 3 }, () => [R(-.5, .5), R(-.4, .4), R(.2, .3)]),
                lobes: [], fibres: [], trail: [], state: 'idle', t: 0, leak: 0, bleb: R(0, TAU), blebSize: 0, nuc: 1, round: 0,
                tex: [R(0, 50), R(0, 50)], out: null };
    k.face = k.dir;
    if (!bare) {
      k.lobes.push(lobe(k, k.dir + R(-.3, .3), 'lam', R(.5, .9)), lobe(k, k.dir + Math.PI + R(-.6, .6), 'stuck', R(.3, .8)));
      if (Math.random() < .6) k.lobes.push(lobe(k, k.dir + R(.9, 1.9) * (Math.random() < .5 ? -1 : 1), 'stuck', R(.2, .5)));
    }
    return k;
  }

  // Protrusions are anchored to the dish, not to the cell. A lamellipodium advances; an anchored one stays where
  // it is while the body moves on, so it swings to the rear and stretches into a tail; then it lets go and snaps back.
  function stepLobes(k, dt, crawling) {
    const rb = k.rb * k.s;
    let px = 0, py = 0, lams = 0, rear = false, ahead = false;
    for (const L of k.lobes) {
      if (L.kind === 'lam') {
        if (!crawling) L.kind = 'back';
        else {
          L.ang += turn(L.ang, k.dir) * dt * .6 + R(-1, 1) * dt * .5;
          if (L.len < L.reach) { const v = k.sp * 2.2 * (1 - .7 * L.len / L.reach); L.x += Math.cos(L.ang) * v * dt; L.y += Math.sin(L.ang) * v * dt; }
          if (Math.abs(turn(L.a, k.dir)) > 1.35) { L.kind = 'stuck'; L.age = 0; L.hold = R(2, 6); }
        }
      } else if (L.kind === 'stuck') {
        L.age += dt; if (!crawling || L.len > L.snap || L.age > L.hold) L.kind = 'back';
      }
      if (L.kind === 'back') {
        const d = Math.hypot(L.x - k.x, L.y - k.y) || 1, v = Math.min(d, (12 + 60 * L.len) * dt);
        L.x += (k.x - L.x) / d * v; L.y += (k.y - L.y) / d * v;
      }
      const dx = L.x - k.x, dy = L.y - k.y;
      L.a = Math.atan2(dy, dx); L.len = Math.max(0, Math.hypot(dx, dy) / rb - CORE);
      if (L.kind === 'lam') { px += Math.cos(L.a) * L.len * L.w; py += Math.sin(L.a) * L.len * L.w; lams++; if (Math.abs(turn(L.a, k.dir)) < 1) ahead = true; }
      else if (Math.cos(L.a - k.face) < -.4) rear = true;
    }
    k.lobes = k.lobes.filter(L => !(L.kind === 'back' && L.len < .04));
    if (crawling) {
      if (!ahead) k.lobes.push(lobe(k, k.dir + R(-.35, .35), 'lam'));
      else if (lams < 2 && k.lobes.length < 5 && Math.random() < dt * .1) k.lobes.push(lobe(k, k.dir + R(.6, 1.2) * (Math.random() < .5 ? -1 : 1), 'lam'));
      if (!rear && k.lobes.length < 5 && Math.random() < dt * .6) k.lobes.push(lobe(k, k.face + Math.PI + R(-.5, .5), 'stuck', R(0, .12)));
    }
    return [px, py];
  }

  // outline of the cell: a body around the nucleus plus its protrusions; a peanut while it divides; blebs while it dies
  function outline(k) {
    const dying = k.state === 'dying', pd = dying ? clamp(k.t / DT, 0, 1) : 0, NP = dying || k.state === 'mitosis' ? 96 : 72;
    const rb = k.rb * k.s, pts = new Array(NP);
    const pm = k.state === 'mitosis' ? k.t / MT : 0, e = pm > .6 ? .975 * ease((pm - .6) / .4) : 0;
    const env = dying ? smooth(.1, .25, pd) * (1 - smooth(.7, .95, pd)) : 0;
    for (let i = 0; i < NP; i++) {
      const th = i / NP * TAU; let sum = 0;
      for (const L of k.lobes) {
        if (L.len <= 0) continue;
        const lam = L.kind === 'lam', x = turn(L.a, th) / (L.w / (1 + (lam ? .25 : .9) * L.len));
        let v = L.len * Math.exp(lam ? -Math.pow(Math.abs(x), 2.4) : -x * x);
        if (lam) v *= 1 + .13 * Math.sin(5 * th + clock * .5 + L.ph) + .08 * Math.sin(8 * th - clock * .8 + L.ph * 2) + .04 * Math.sin(13 * th + clock * 1.7 + L.ph * 3);
        sum += v * v * v;
      }
      const cn = Math.cos(th - k.nrot), sn = Math.sin(th - k.nrot), hug = (k.na * k.nb / Math.hypot(k.nb * cn, k.na * sn) + 7) / k.rb;
      const core = hug * (1 + .1 * Math.sin(2 * th + k.ph + clock * .22) + .08 * Math.sin(3 * th - k.ph * 2 - clock * .17) + .04 * Math.sin(5 * th + k.ph * 3 + clock * .4));
      let r = lerp(core, .8, k.round) + Math.cbrt(sum) * (1 - .5 * k.round);
      if (e > 0) { const f = th - k.maxis, s2 = Math.sin(2 * f);
        r = .8 * (1 + .08 * e) * Math.sqrt(Math.max(1e-4, e * e * Math.cos(2 * f) + Math.sqrt(1 - e * e * e * e * s2 * s2))); }
      if (dying) { let b = 0;
        for (const q of k.blebs) { const x = turn(q[0], th) / q[1]; b = Math.max(b, q[4] * Math.max(0, Math.sin(clock * q[2] + q[3])) * Math.exp(-x * x)); }
        r *= (1 - .36 * ease(pd)) * (1 + .4 * env * b); }
      pts[i] = [k.x + Math.cos(th) * rb * r, k.y + Math.sin(th) * rb * r];
    }
    return pts;
  }
  function trace(q, pts, grow = 1, cx = 0, cy = 0) {
    q.beginPath();
    const n = pts.length, P = grow === 1 ? pts : pts.map(p => [cx + (p[0] - cx) * grow, cy + (p[1] - cy) * grow]);
    q.moveTo((P[n - 1][0] + P[0][0]) / 2, (P[n - 1][1] + P[0][1]) / 2);
    for (let i = 0; i < n; i++) { const a = P[i], b = P[(i + 1) % n]; q.quadraticCurveTo(a[0], a[1], (a[0] + b[0]) / 2, (a[1] + b[1]) / 2); }
    q.closePath();
  }
  function nucleusPath(q, k, grow = 1, pad = 0, bleb = true) {                       // in the frame of the nucleus
    const na = k.na * k.s * grow + pad, nb = k.nb * k.s * grow + pad, n = 40;
    q.beginPath();
    for (let i = 0; i < n; i++) {
      const f = i / n * TAU, r = 1 + k.nw[2] * Math.sin(2 * f + k.nw[0]) + k.nw[3] * Math.sin(3 * f + k.nw[1] + clock * .22);
      const x = Math.cos(f) * na * r, y = Math.sin(f) * nb * r; if (i) q.lineTo(x, y); else q.moveTo(x, y);
    }
    q.closePath();
    if (bleb && k.blebSize > .02) { const bx = Math.cos(k.bleb) * na * 1.04, by = Math.sin(k.bleb) * nb * 1.04, br = (2 + 4.2 * k.blebSize) * k.s + pad * .6;
      q.moveTo(bx + br, by); q.arc(bx, by, br, 0, TAU); }
  }
  const blebAt = k => { const cs = Math.cos(k.nrot), sn = Math.sin(k.nrot), u = Math.cos(k.bleb) * k.na * k.s * 1.04, v = Math.sin(k.bleb) * k.nb * k.s * 1.04;
    return [k.x + u * cs - v * sn, k.y + u * sn + v * cs]; };

  function enter(k, state) {
    k.state = state; k.t = 0;
    k.fibres = k.lobes.filter(L => L.len > .25).map(L => ({ x: L.x, y: L.y, a: 1 }));
    if (state === 'mitosis') {
      k.maxis = k.face;
      k.chr = Array.from({ length: 22 }, (_, i) => { const a = R(0, TAU), d = Math.sqrt(Math.random()) * .8;
        return { u: (i / 21) * 2 - 1 + R(-.06, .06), v: R(-1, 1), px: Math.cos(a) * d, py: Math.sin(a) * d, rot: R(0, Math.PI), len: R(.75, 1.2), j: R(0, TAU) }; });
    }
    if (state === 'dying') {
      k.blebs = Array.from({ length: 14 }, (_, i) => [i / 14 * TAU + R(-.2, .2), R(.13, .21), R(2.4, 5.5), R(0, TAU), R(.45, 1)]);
      k.frags = Array.from({ length: 6 }, (_, i) => [i / 6 * TAU + R(-.4, .4), R(.2, .55), R(.26, .44), R(.7, 1.3)]);
    }
  }
  function divide(k) {
    const ax = k.maxis, off = k.rb * k.s * .61, pair = [];
    for (const sign of [0, Math.PI]) {
      const d = cell(k.x + Math.cos(ax + sign) * off, k.y + Math.sin(ax + sign) * off, .72 * k.s, true);
      Object.assign(d, { dir: ax + sign, face: ax + sign, fade: 1, round: 1, nuc: .5, leak: .46, state: 'newborn', t: 0,
                         rb: k.rb, na: k.na, nb: k.nb, nrot: ax + Math.PI / 2, sp: k.sp * R(.9, 1.1) });
      pair.push(d);
    }
    pair[0].sister = pair[1]; pair[1].sister = pair[0];
    cells.splice(cells.indexOf(k), 1, pair[0], pair[1]); divisions++;
  }

  function stepCell(k, dt) {
    k.fade = Math.min(1, k.fade + dt * .9); k.s = Math.min(1, k.s + dt * .03); k.t += dt;
    const crawling = k.state === 'idle' || k.state === 'rupture' || (k.state === 'newborn' && k.round < .55);
    const pull = stepLobes(k, dt, crawling);
    for (const f of k.fibres) f.a -= dt * (k.state === 'mitosis' ? .1 : .22);
    if (k.fibres.length) k.fibres = k.fibres.filter(f => f.a > 0);
    if (k.state === 'dying') { k.round = Math.min(1, k.round + dt * .5); k.leak = .4 * smooth(.18, .45, k.t / DT); return; }
    if (crawling) {
      k.dir += R(-1, 1) * dt * 1.3;
      if (Math.random() < dt * .06) k.dir += R(-1.8, 1.8);              // cells change their mind
      const m = 70;
      if (k.leaving) k.dir = k.exit;
      else {
        if (k.x < m) k.dir += turn(k.dir, 0) * .08;
        if (k.x > W - m) k.dir += turn(k.dir, Math.PI) * .08;
        if (k.y < m) k.dir += turn(k.dir, Math.PI / 2) * .08;
        if (k.y > H - m) k.dir += turn(k.dir, -Math.PI / 2) * .08;
      }
      const p = Math.hypot(pull[0], pull[1]);
      if (p > .02) {
        const h = Math.atan2(pull[1], pull[0]), surge = .7 + .3 * Math.sin(clock * .8 + k.ph);   // crawling comes in pushes
        const v = k.sp * clamp(p / .3, 0, 1.15) * surge * (1 - k.round);
        k.face += turn(k.face, h) * Math.min(1, dt * 2.5);
        k.x += Math.cos(h) * v * dt; k.y += Math.sin(h) * v * dt;
      }
      k.nrot += turnAxis(k.nrot, k.face) * dt * .45;
    }
    for (const o of cells) {
      if (o === k) continue;
      const dx = k.x - o.x, dy = k.y - o.y, dd = Math.hypot(dx, dy), min = (k.rb * k.s + o.rb * o.s) * .95;
      if (dd > 0 && dd < min) { const p = (min - dd) / min; k.x += dx / dd * p * 26 * dt; k.y += dy / dd * p * 26 * dt; }
    }
    const tr = k.trail, n = tr.length;
    if (!n || Math.hypot(k.x - tr[n - 1][0], k.y - tr[n - 1][1]) > 4) { tr.push([k.x, k.y]); if (n > 64) tr.shift(); }

    if (k.state === 'rupture') {
      const p = k.t / RT;
      k.blebSize = p < .17 ? ease(p / .17) : 1 - smooth(.17, .9, p);
      if (p >= .17 && !k.burst) { k.burst = true; ruptures++; }
      k.leak = p < .17 ? 0 : p < .24 ? ease((p - .17) / .07) : Math.exp(-(p - .24) * 4.6);
      if (p >= 1) { k.state = 'idle'; k.t = 0; k.leak = 0; k.burst = false; k.blebSize = 0; k.bleb = R(0, TAU); }
    } else if (k.state === 'mitosis') {
      const p = k.t / MT, nebd = ease((p - .12) / .1);
      k.round = ease(p / .16); k.nuc = 1 - nebd; k.leak = .46 * nebd;
      if (p >= 1) divide(k);
    } else if (k.state === 'newborn') {
      const p = clamp(k.t / 6, 0, 1);
      k.round = 1 - ease(p); k.nuc = lerp(.5, 1, ease(p * 1.6)); k.leak = .46 * (1 - ease(p * 1.3));
      if (p >= 1) { k.state = 'idle'; k.t = 0; k.sister = null; k.leak = 0; }
    } else { k.round = Math.max(0, k.round - dt * .4); k.nuc = 1; }
    if (k.leaving && (k.x < -110 || k.x > W + 110 || k.y < -110 || k.y > H + 110)) k.gone = true;
  }

  // one schedule for the whole field: there is always a division under way, and ruptures keep coming
  const due = { mitosis: demo ? 1e9 : 1.2, rupture: demo ? 1e9 : 2.5, death: demo ? 1e9 : 22 };
  function pick() {
    const ok = cells.filter(k => k.state === 'idle' && !k.leaving && k.fade >= 1 && k.s >= .95 && k.round < .05
                                 && k.x > 60 && k.x < W - 60 && k.y > 60 && k.y < H - 70);
    return ok.length ? ok[Math.floor(Math.random() * ok.length)] : null;
  }
  function schedule(dt) {
    for (const key in due) due[key] -= dt;
    const busy = target / 8;
    if (due.mitosis <= 0 && cells.filter(k => k.state === 'mitosis').length < 1 + busy) {
      const k = pick(); if (k) { enter(k, 'mitosis'); due.mitosis = R(5, 8) / busy; } else due.mitosis = .5;
    }
    if (due.rupture <= 0) {
      const k = pick(); if (k) { enter(k, 'rupture'); k.fibres = []; due.rupture = R(3.5, 7) / busy; } else due.rupture = .5;
    }
    if (due.death <= 0) {
      const k = pick(); if (k && cells.length > target) { enter(k, 'dying'); deaths++; due.death = R(20, 34) / busy; } else due.death = 3;
    }
    // the field does not fill up: when it is crowded, a cell crawls away
    if (cells.filter(k => !k.leaving && k.state !== 'dying').length > target + 1) {
      const k = pick();
      if (k) { k.leaving = true; k.exit = [[k.x, Math.PI], [W - k.x, 0], [k.y, -Math.PI / 2], [H - k.y, Math.PI / 2]].sort((a, b) => a[0] - b[0])[0][1]; }
    }
    while (cells.length < target - 2) {
      const side = Math.floor(R(0, 4)), x = side === 0 ? -50 : side === 1 ? W + 50 : R(80, W - 80), y = side === 2 ? -50 : side === 3 ? H + 50 : R(60, H - 60);
      const k = cell(x, y); k.dir = k.face = [0, Math.PI, Math.PI / 2, -Math.PI / 2][side]; k.fade = 1; k.lobes = []; cells.push(k);
    }
  }

  function blob(q, x, y, r, rgb, a) {
    const gr = q.createRadialGradient(x, y, 0, x, y, r);
    gr.addColorStop(0, `rgba(${rgb},${a})`); gr.addColorStop(1, `rgba(${rgb},0)`);
    q.fillStyle = gr; q.beginPath(); q.arc(x, y, r, 0, TAU); q.fill();
  }

  // the fluorescence of one cell; `sharp` adds the detail that the out-of-focus haze does not carry
  function paint(q, k, sharp) {
    const pts = k.out; if (!pts) return;
    const al = k.fade, rb = k.rb * k.s, dying = k.state === 'dying', pd = dying ? clamp(k.t / DT, 0, 1) : 0;
    const pm = k.state === 'mitosis' ? k.t / MT : 0, e = pm > .6 ? ease((pm - .6) / .4) : 0;
    const body = dying ? 1 - smooth(.55, .9, pd) : 1;
    const cyt = (.02 + .66 * k.leak) * (1 + .3 * k.round) * al * body;   // a rounded cell is a thicker cell

    // cytoplasm: brightest where the cell is thick, around the nucleus, and thin towards the edge
    const lit = (cx, cy, rad, wgt, edge) => {
      const gr = q.createRadialGradient(cx, cy, 2, cx, cy, rad);
      gr.addColorStop(0, `rgba(34,250,100,${Math.min(1, cyt * 1.3 * wgt)})`); gr.addColorStop(.34, `rgba(26,236,92,${Math.min(1, cyt * wgt)})`);
      gr.addColorStop(1, `rgba(16,205,80,${cyt * edge * wgt})`);
      q.fillStyle = gr;
      if (!sharp) { trace(q, pts); q.fill(); return; }
      const was = q.globalAlpha; q.globalAlpha = was / 3;
      for (const sc of [1, .87, .72]) { trace(q, pts, sc, k.x, k.y); q.fill(); }
      q.globalAlpha = was;
    };
    if (e > .02) {
      const o = rb * .61 * e, rad = rb * lerp(1.05, .66, e);
      for (const sg of [-1, 1]) lit(k.x + Math.cos(k.maxis) * o * sg, k.y + Math.sin(k.maxis) * o * sg, rad, lerp(.5, 1, e), .3 * (1 - e));
    } else lit(k.x, k.y, rb * lerp(1.9, 1.0, k.round), 1, lerp(.14, .3, k.round));
    if (sharp && cyt > .03) {
      q.save(); trace(q, pts); q.clip(); q.globalAlpha = Math.min(1, cyt * 1.25);
      const S = rb * 4.4; q.drawImage(cyto, k.tex[0], k.tex[1], 200, 200, k.x - S / 2, k.y - S / 2, S, S);
      if (k.state === 'rupture' && k.burst) {                           // the reporter pours out at the break and spreads
        const fp = clamp((k.t - RT * .17) / 1.2, 0, 1);
        if (fp < 1) { q.globalAlpha = 1; const [bx, by] = blebAt(k); blob(q, bx, by, rb * (.3 + 1.7 * ease(fp)), '40,255,110', .6 * (1 - fp) * al); }
      }
      q.restore();
      q.lineWidth = .6; q.lineCap = 'round';                            // retraction fibres hold a rounded cell to the dish
      for (const f of k.fibres) {
        const a = Math.atan2(f.y - k.y, f.x - k.x), r0 = rb * .78;
        q.strokeStyle = `rgba(90,245,145,${Math.min(.5, cyt * .7) * clamp(f.a * 2, 0, 1) * k.round})`;
        q.beginPath(); q.moveTo(k.x + Math.cos(a) * r0, k.y + Math.sin(a) * r0); q.lineTo(f.x, f.y); q.stroke();
      }
    }
    if (k.state === 'newborn' && k.sister && k.id < k.sister.id && sharp) {   // the bridge that still joins two daughters
      q.strokeStyle = `rgba(90,245,145,${.35 * (1 - k.t / 6)})`; q.lineWidth = 1.1;
      q.beginPath(); q.moveTo(k.x, k.y); q.lineTo(k.sister.x, k.sister.y); q.stroke();
    }

    // Two channels. Green is the NLS reporter, which is only in the nucleus while the envelope is intact.
    // Red is a histone, which is the chromatin itself: it stays where the DNA is whatever the envelope does.
    if (dying) {                                                        // the nucleus condenses, then breaks up
      const whole = 1 - smooth(.3, .48, pd), out = 1 - smooth(.78, 1, pd), kept = 1 - smooth(.3, .7, pd);   // the reporter is lost before the chromatin
      if (whole > .01) {
        q.save(); q.translate(k.x, k.y); q.rotate(k.nrot);
        nucleusPath(q, k, 1 - .42 * smooth(0, .32, pd), 0, false);
        q.fillStyle = `rgba(40,250,105,${.7 * whole * kept * al})`; q.fill();
        q.fillStyle = `rgba(${RED},${Math.min(1, (.5 + .4 * smooth(0, .3, pd)) * whole * al)})`; q.fill();
        q.restore();
      }
      const fr = smooth(.3, .48, pd);
      if (fr > .01) for (const [a, d, sz, drift] of k.frags) {
        const rad = rb * d * (.35 + .55 * smooth(.3, .62, pd) + 1.1 * drift * smooth(.62, 1, pd));
        const x = k.x + Math.cos(a) * rad, y = k.y + Math.sin(a) * rad, r = k.na * sz * (1.15 - .35 * pd) * (sharp ? 1 : 1.5);
        blob(q, x, y, r, '50,255,115', .6 * fr * out * kept * al);
        blob(q, x, y, r, RED, .9 * fr * out * al);
      }
      return;
    }

    const chromatin = (1 - smooth(.04, .18, pm)) * al;                  // spread through the nucleus until the chromosomes condense
    if (k.nuc > .02 || chromatin > .02) {
      const bright = (1 - .94 * k.leak) * k.nuc * al * (sharp ? .8 : 1), na = k.na * k.s, there = Math.max(k.nuc, chromatin);
      q.save(); q.translate(k.x, k.y); q.rotate(k.nrot);
      if (sharp && !light && k.nuc > .02) {                             // hardly any cytoplasm lies over or under the nucleus
        const ga = q.globalAlpha; q.globalAlpha = 1;
        q.globalCompositeOperation = 'multiply'; q.fillStyle = `rgba(0,0,0,${.93 * k.nuc})`; nucleusPath(q, k, 1, 0, false); q.fill();
        q.globalCompositeOperation = ADD; q.globalAlpha = ga;
      }
      if (k.nuc > .02) {
        const gr = q.createRadialGradient(0, 0, 1, 0, 0, na * 1.15);
        gr.addColorStop(0, `rgba(48,255,112,${bright})`); gr.addColorStop(.72, `rgba(32,242,96,${bright})`); gr.addColorStop(1, `rgba(22,214,84,${bright * .85})`);
        q.fillStyle = gr; nucleusPath(q, k, sharp ? 1 : 1.08); q.fill();
      }
      if (chromatin > .02) {                                            // chromatin is denser towards the edge of the nucleus
        const rd = q.createRadialGradient(0, 0, 1, 0, 0, na * 1.1), ra = chromatin * (sharp ? HIST : HIST * .45);
        rd.addColorStop(0, `rgba(${RED},${ra * .8})`); rd.addColorStop(.7, `rgba(${RED},${ra})`); rd.addColorStop(1, `rgba(${RED},${ra * 1.1})`);
        q.fillStyle = rd; nucleusPath(q, k, 1, 0, false); q.fill();
      }
      if (sharp) {
        q.save(); nucleusPath(q, k); q.clip(); q.globalCompositeOperation = 'multiply';
        q.globalAlpha = (light ? .25 : .6) * there; q.drawImage(chrom, k.tex[0], k.tex[1], 110, 110, -na, -na, na * 2, na * 2);
        q.globalAlpha = 1;
        for (const [u, v, r] of k.nucleoli) blob(q, u * na, v * k.nb * k.s, r * na * 1.5, '0,0,0', (light ? .2 : .62) * there);
        q.restore();
      }
      q.restore();
    }

    if (pm > .04 && k.chr) {                                            // chromosomes condense, line up and are pulled apart
      const ax = k.maxis, cxs = Math.cos(ax), sxs = Math.sin(ax), acx = -sxs, acy = cxs, L = rb * .4;
      const vis = smooth(.04, .16, pm) * al, con = smooth(.2, .42, pm), sep = rb * .58 * ease((pm - .54) / .3), tel = smooth(.8, 1, pm);
      const cn = Math.cos(k.nrot), sn = Math.sin(k.nrot), na = k.na * k.s, nb = k.nb * k.s;
      q.lineCap = 'round';
      for (const sg of sep > 0 ? [-1, 1] : [0]) {
        q.beginPath();
        for (const ch of k.chr) {
          const u = ch.u * lerp(1, .55, tel), bow = sg * 5 * u * u * (sep / (rb * .58));
          const mx = cxs * (sg * sep + bow + ch.v * 2.2 * (1 - tel)) + acx * L * u, my = sxs * (sg * sep + bow + ch.v * 2.2 * (1 - tel)) + acy * L * u;
          const px = (ch.px * na) * cn - (ch.py * nb) * sn, py = (ch.px * na) * sn + (ch.py * nb) * cn;
          const x = k.x + lerp(px, mx, con) + Math.sin(clock * 2.3 + ch.j) * .7, y = k.y + lerp(py, my, con) + Math.cos(clock * 2 + ch.j) * .7;
          const tilt = lerp(ch.rot, ax + .35 * Math.sin(ch.j), con), arm = 2.9 * ch.len * (1 - .4 * tel);
          q.moveTo(x - Math.cos(tilt) * arm, y - Math.sin(tilt) * arm); q.lineTo(x + Math.cos(tilt) * arm, y + Math.sin(tilt) * arm);
        }
        if (sharp && !light) {                                          // chromosomes push the soluble reporter aside
          q.globalCompositeOperation = 'multiply'; q.lineWidth = 4.2; q.strokeStyle = `rgba(0,0,0,${.85 * vis * k.leak / .46})`; q.stroke();
          q.globalCompositeOperation = ADD;
        }
        q.lineWidth = sharp ? 2.2 : 5; q.strokeStyle = `rgba(255,44,70,${(sharp ? 1 : .24) * vis * (1 - .3 * tel)})`; q.stroke();
        if (sharp) { q.lineWidth = .8; q.strokeStyle = `rgba(255,150,150,${.3 * vis * (1 - tel)})`; q.stroke(); }
        if (tel > .01) {                                                // two new nuclei begin to form around them
          q.save(); q.translate(k.x + cxs * sg * sep, k.y + sxs * sg * sep); q.rotate(ax + Math.PI / 2);
          q.beginPath(); q.ellipse(0, 0, na * .72 * .8, nb * .72 * .8, 0, 0, TAU);
          q.fillStyle = `rgba(${RED},${HIST * .8 * tel * al})`; q.fill(); q.fillStyle = `rgba(36,245,100,${.22 * tel * al})`; q.fill(); q.restore();
        }
      }
    }
  }

  function label(x, y, text, color, al) {
    g.font = '700 9px ui-monospace, Menlo, monospace';
    const w = g.measureText(text).width + 10;
    x = Math.min(x, W - w - 6);
    g.fillStyle = `rgba(${INK.textBg},${(light ? .86 : .72) * al})`; g.beginPath(); g.roundRect(x, y - 9, w, 13, 3); g.fill();
    g.fillStyle = color; g.fillText(text, x + 5, y + 1);
  }

  function mark(k) {                                                    // what the software draws on top
    const al = k.fade, dying = k.state === 'dying', tr = k.trail;
    g.lineWidth = 1; g.lineCap = 'round';
    for (let i = 1; i < tr.length; i++) {
      g.strokeStyle = `rgba(${INK.trail},${.4 * al * i / tr.length})`;
      g.beginPath(); g.moveTo(tr[i - 1][0], tr[i - 1][1]); g.lineTo(tr[i][0], tr[i][1]); g.stroke();
    }
    const na = k.na * k.s, nb = k.nb * k.s;
    if (dying) {
      const p = clamp(k.t / DT, 0, 1), s = 6;
      g.strokeStyle = `rgba(255,157,60,${(1 - p * .7) * al})`; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(k.x - s, k.y - s); g.lineTo(k.x + s, k.y + s); g.moveTo(k.x - s, k.y + s); g.lineTo(k.x + s, k.y - s); g.stroke();
      if (p < .85) label(k.x + na + 10, k.y - nb - 8, 'DEATH', `rgba(${INK.death},1)`, al);
      return;
    }
    if (k.state === 'mitosis') {
      const p = k.t / MT;
      g.strokeStyle = `rgba(255,214,10,${.9 * al})`; g.lineWidth = 1.3; g.setLineDash([4, 3]);
      trace(g, k.out, 1.07, k.x, k.y); g.stroke(); g.setLineDash([]);
      label(k.x + k.rb * k.s * .9, k.y - k.rb * k.s * .95, p < .2 ? 'PROPHASE' : p < .54 ? 'METAPHASE' : p < .76 ? 'ANAPHASE' : 'CYTOKINESIS', `rgba(${INK.mito},1)`, al);
      return;
    }
    if (k.state === 'newborn' && k.sister && cells.includes(k.sister) && k.id < k.sister.id) {
      g.strokeStyle = `rgba(255,214,10,${.5 * (1 - k.t / 6)})`; g.lineWidth = 1; g.setLineDash([2, 4]);
      g.beginPath(); g.moveTo(k.x, k.y); g.lineTo(k.sister.x, k.sister.y); g.stroke(); g.setLineDash([]);
    }
    if (k.nuc < .4) return;
    g.save(); g.translate(k.x, k.y); g.rotate(k.nrot);
    g.strokeStyle = `rgba(${INK.outline},${.7 * al * k.nuc})`; g.lineWidth = 1; g.lineJoin = 'round';
    nucleusPath(g, k, 1, 2.5); g.stroke();
    g.restore();
    if (k.state === 'rupture' && k.burst) {
      label(k.x + na + 10, k.y - nb - 9, 'RUPTURE  ' + Math.max(Math.round((k.t - RT * .17) * 12), 0) + ' min', `rgba(${INK.rupt},1)`, al);
    }
    g.fillStyle = `rgba(${INK.id},${.55 * al})`; g.font = '600 8.5px ui-monospace, Menlo, monospace';
    g.fillText(String(k.id).padStart(2, '0'), k.x + na + 7, k.y + nb + 10);
  }

  // ------------------------------------------------------------------ neurons
  const MAXB = 120, MAXD = 7;
  function neurite(x, y, dir, vigour, depth = 0) {
    // each order of branch is thinner and shorter than its parent, as in a root system
    return { pts: [[x, y]], dir, vigour, depth, len: 0, growing: true, pause: 0, fork: R(18, 44),
             max: R(80, 150) * Math.pow(.8, depth), wob: R(0, TAU) };
  }
  function neuron(x, y) {
    const n = { x, y, r: R(8, 10), arbor: [], age: 0, life: R(30, 40), state: 'grow', fade: 0 };
    const a = R(0, TAU), roots = 6 + Math.floor(R(0, 3)); n.axis = a;
    for (let i = 0; i < roots; i++) {
      const d = a + i / roots * TAU + R(-.25, .25);
      n.arbor.push(neurite(x + Math.cos(d) * n.r * .9, y + Math.sin(d) * n.r * .9, d, i === 0 ? 1 : R(.7, .9)));
    }
    return n;
  }
  function placeNeuron() {
    for (let i = 0; i < 40; i++) {
      const x = R(W * .12, W * .88), y = R(H * .2, H * .78);
      if (neurons.every(o => Math.hypot(o.x - x, o.y - y) > Math.min(420, W * .3))) { neurons.push(neuron(x, y)); return; }
    }
  }
  function stepNeuron(n, dt) {
    n.age += dt; n.fade = Math.min(1, n.fade + dt * .7);
    if (n.state === 'grow' && n.age > n.life) n.state = 'prune';
    if (n.state === 'prune') {
      let remaining = 0;
      for (const b of n.arbor) {
        b.growing = false;
        let cut = 150 * dt;
        while (cut > 0 && b.pts.length > 1) {
          const p = b.pts[b.pts.length - 1], q = b.pts[b.pts.length - 2], d = Math.hypot(p[0] - q[0], p[1] - q[1]);
          if (d <= cut) { b.pts.pop(); cut -= d; b.len -= d; } else { p[0] = lerp(p[0], q[0], cut / d); p[1] = lerp(p[1], q[1], cut / d); b.len -= cut; cut = 0; }
        }
        remaining += b.pts.length - 1;
      }
      if (remaining === 0) { n.fade -= dt * 1.6; if (n.fade <= 0) n.gone = true; }
      return;
    }
    for (const b of [...n.arbor]) {
      if (!b.growing) continue;
      if (b.pause > 0) { b.pause -= dt; continue; }
      if (Math.random() < dt * .3) b.pause = R(.2, 1.1);                // growth cones stop and start
      b.dir += R(-1, 1) * dt * 1.5 + Math.sin(clock * .7 + b.wob) * dt * .3;
      const tip = b.pts[b.pts.length - 1], v = 30 * b.vigour * Math.pow(.93, b.depth);
      const x = tip[0] + Math.cos(b.dir) * v * dt, y = tip[1] + Math.sin(b.dir) * v * dt;
      if (x < 8 || x > W - 8 || y < 8 || y > H - 8) { b.growing = false; continue; }
      const prev = b.pts.length > 1 ? b.pts[b.pts.length - 2] : null;
      b.len += Math.hypot(x - tip[0], y - tip[1]);
      if (!prev || Math.hypot(x - prev[0], y - prev[1]) > 6) b.pts.push([x, y]); else { tip[0] = x; tip[1] = y; }
      if (b.len > b.max) b.growing = false;
      if (b.len > b.fork && b.depth < MAXD && n.arbor.length < MAXB) {  // the tip forks, and both arms carry on
        b.fork = b.len + R(20, 52) * Math.pow(.92, b.depth);
        const side = (Math.random() < .5 ? -1 : 1), spread = R(.45, .85);
        n.arbor.push(neurite(x, y, b.dir + side * spread, b.vigour * R(.8, .95), b.depth + 1));
        b.dir -= side * spread * R(.25, .5);
      }
    }
  }
  function paintNeuron(q, n, sharp) {
    const al = clamp(n.fade, 0, 1), beads = [], cones = [];
    q.lineCap = 'round'; q.lineJoin = 'round';
    for (const b of n.arbor) {
      const P = b.pts, m = P.length;
      if (m < 2) continue;
      const base = 2.5 * Math.max(.5, b.vigour) * Math.pow(.78, b.depth);
      const cut = sharp && m > 5 ? [0, m >> 1, m - 1] : [0, m - 1];      // a shaft tapers: it is drawn in two pieces
      for (let c = 0; c < cut.length - 1; c++) {
        const i0 = cut[c], i1 = cut[c + 1], t = (i0 + i1) / 2 / m;
        q.strokeStyle = sharp ? `rgba(${196 - 40 * t},${132 + 24 * t},255,${(.62 - .22 * t) * al})` : `rgba(150,90,255,${(.30 - .12 * t) * al})`;
        q.lineWidth = Math.max(.45, base * (1 - .55 * t)) * (sharp ? 1 : 2);
        q.beginPath(); q.moveTo(P[i0][0], P[i0][1]);
        for (let i = i0 + 1; i < i1; i++) q.quadraticCurveTo(P[i][0], P[i][1], (P[i][0] + P[i + 1][0]) / 2, (P[i][1] + P[i + 1][1]) / 2);
        q.lineTo(P[i1][0], P[i1][1]); q.stroke();
      }
      if (sharp && m > 6 && b.depth < 3)                               // varicosities along the thicker shafts
        for (let i = 3 + Math.floor(b.wob) % 3; i < m - 2; i += 4 + (i * 7 + Math.floor(b.wob * 3)) % 5) beads.push(P[i][0], P[i][1], base * .75);
      if (b.growing) cones.push(b);
    }
    if (beads.length) {
      q.fillStyle = `rgba(230,205,255,${.2 * al})`; q.beginPath();
      for (let i = 0; i < beads.length; i += 3) { q.moveTo(beads[i] + beads[i + 2], beads[i + 1]); q.arc(beads[i], beads[i + 1], beads[i + 2], 0, TAU); }
      q.fill();
    }
    if (cones.length) {                                                 // growth cones: a veil, and filopodia that feel the way
      q.fillStyle = `rgba(200,160,255,${(sharp ? .3 : .16) * al})`; q.beginPath();
      for (const b of cones) {
        const P = b.pts, e = P[P.length - 1], p2 = P[P.length - 2];
        const dir = b.cone = Math.atan2(e[1] - p2[1], e[0] - p2[0]), sz = b.sz = 5 * Math.max(.6, b.vigour) * Math.pow(.92, b.depth);
        q.moveTo(e[0] - Math.cos(dir) * sz * .4, e[1] - Math.sin(dir) * sz * .4);
        for (let i = -3; i <= 3; i++) { const a = dir + i * .36, L = sz * (1.05 + .25 * Math.sin(clock * 2.6 + i * 1.3 + b.wob));
          q.lineTo(e[0] + Math.cos(a) * L, e[1] + Math.sin(a) * L); }
        q.closePath();
      }
      q.fill();
      if (sharp) {
        q.strokeStyle = `rgba(235,215,255,${.75 * al})`; q.lineWidth = .6; q.beginPath();
        for (const b of cones) {
          const e = b.pts[b.pts.length - 1], nf = b.depth < 3 ? 6 : 4;
          for (let i = 0; i < nf; i++) {
            const a = b.cone + (i - (nf - 1) / 2) * .4 + Math.sin(clock * 2.4 + i * 1.7 + b.wob) * .22;
            const L = b.sz * (1.5 + .8 * Math.sin(clock * 3.1 + i * 2.3 + b.wob));
            q.moveTo(e[0], e[1]); q.lineTo(e[0] + Math.cos(a) * L, e[1] + Math.sin(a) * L);
          }
        }
        q.stroke();
      }
    }
    const r = n.r;
    q.save(); q.translate(n.x, n.y); q.rotate(n.axis);                  // soma, drawn out towards the longest neurite
    const soma = q.createRadialGradient(0, 0, 1, 0, 0, r * 1.9);
    soma.addColorStop(0, `rgba(225,205,255,${.8 * al})`); soma.addColorStop(.5, `rgba(165,110,255,${.7 * al})`);
    soma.addColorStop(1, 'rgba(150,100,245,0)');
    q.fillStyle = soma; q.beginPath(); q.ellipse(r * .15, 0, r * 1.9, r * 1.45, 0, 0, TAU); q.fill();
    q.restore();
    blob(q, n.x, n.y, r * .8, '60,255,125', .5 * al);                   // its nucleus, in both channels
    blob(q, n.x, n.y, r * .8, RED, .45 * al);
  }
  const arborLength = n => n.arbor.reduce((s, b) => s + Math.max(b.len, 0), 0);

  // ------------------------------------------------------------------ the field
  function populate() {
    const cols = Math.max(2, Math.round(Math.sqrt(target * W / H))), rows = Math.ceil(target / cols);
    for (let i = 0; i < target; i++) {
      const k = cell(50 + (i % cols + R(.25, .75)) / cols * (W - 100), 50 + (Math.floor(i / cols) + R(.25, .75)) / rows * (H - 110));
      k.fade = 1; cells.push(k);
    }
    const nn = demo ? 0 : W * H > 1500000 ? 3 : W * H > 520000 ? 2 : 1;
    for (let i = 0; i < nn; i++) placeNeuron();
    for (let i = 0, n = Math.round(W * H / 400000) + 1; i < n; i++)
      ghosts.push({ x: R(0, W), y: R(0, H), r: R(45, 85), sq: R(.6, .9), rot: R(0, TAU), vx: R(-3, 3), vy: R(-2, 2), a: R(.02, .045) });
    for (let i = 0, n = Math.round(W * H / 80000); i < n; i++)
      specks.push({ x: R(0, W), y: R(0, H), r: R(.7, 1.5), a: R(.08, .22), vx: R(-2, 2), vy: R(-2, 2), ph: R(0, TAU) });
    if (demo && cells[0]) {
      const k = cells[0], mx = W / 2 - k.x, my = H / 2 - k.y; k.x += mx; k.y += my; for (const L of k.lobes) { L.x += mx; L.y += my; }
      for (let i = 0; i < 80; i++) step(.05);
      enter(k, demo === 'death' ? 'dying' : demo); if (demo === 'rupture') k.fibres = [];
      for (let i = 0; i < at * 20; i++) step(.05);
    } else for (let i = 0, n = still ? 300 : 110; i < n; i++) step(.05);
  }
  function step(dt) {
    clock += dt;
    for (const n of [...neurons]) { stepNeuron(n, dt); if (n.gone) { neurons.splice(neurons.indexOf(n), 1); placeNeuron(); } }
    for (const k of [...cells]) { stepCell(k, dt); if ((k.state === 'dying' && k.t > DT) || k.gone) cells.splice(cells.indexOf(k), 1); }
    if (!demo) schedule(dt);
    for (const s of ghosts) { s.x += s.vx * dt; s.y += s.vy * dt; if (s.x < -100) s.x = W + 90; if (s.x > W + 100) s.x = -90; if (s.y < -100) s.y = H + 90; if (s.y > H + 100) s.y = -90; }
    for (const s of specks) { s.x += (s.vx + Math.sin(clock * .6 + s.ph) * 2) * dt; s.y += (s.vy + Math.cos(clock * .5 + s.ph) * 2) * dt;
      if (s.x < -5) s.x = W + 4; if (s.x > W + 5) s.x = -4; if (s.y < -5) s.y = H + 4; if (s.y > H + 5) s.y = -4; }
  }

  let noiseAt = -1, ni = 0, nx = 0, ny = 0, benching = false, hudAt = -1, resting = false, restAt = 0;
  function spread(q, pat, ox, oy) { q.save(); q.translate(-ox, -oy); q.fillStyle = pat; q.fillRect(ox, oy, F.width, F.height); q.restore(); }

  function frame(now) {
    if (!still && !freeze && !benching) {
      requestAnimationFrame(frame);
      if (ready && now - restAt > 400) {                                  // look twice a second whether to rest
        restAt = now;
        try { const d = window.parent.document;                           // the app page around this frame
          resting = !d.hasFocus() || !!d.querySelector('[data-testid="stProgress"], [data-testid="stSpinner"]'); } catch (e) { resting = false; }
      }
      if (ready && resting && !force) { last = now; return; }             // window in the background, or an analysis is running
      if (ready && now - last < 45 && !force) return;
      force = false;
    }
    if (!ready) { size(); if (W < 60 || H < 60) { if (still || freeze) requestAnimationFrame(frame); return; } populate(); ready = true; last = now; }
    const dt = (still || freeze) ? 0 : Math.min((now - last) / 1000, .07); last = now;
    if (dt) step(dt);
    for (const k of cells) k.out = outline(k);

    // 1. the haze: everything that glows, drawn small and stretched, so that it spreads like light out of focus
    gb.setTransform(1, 0, 0, 1, 0, 0); gb.globalCompositeOperation = 'source-over'; gb.globalAlpha = 1;
    gb.fillStyle = '#000'; gb.fillRect(0, 0, B.width, B.height);
    gb.setTransform(BS, 0, 0, BS, 0, 0); gb.globalCompositeOperation = 'lighter';
    for (const s of ghosts) { gb.save(); gb.translate(s.x, s.y); gb.rotate(s.rot); gb.scale(1, s.sq); blob(gb, 0, 0, s.r, '40,230,110', s.a * 1.5); gb.restore(); }
    if (!off.includes('neurons')) for (const n of neurons) paintNeuron(gb, n, false);
    if (!off.includes('cells')) for (const k of cells) paint(gb, k, false);

    // 2. the camera image: haze plus the in-focus picture, at the resolution of the camera
    gf.setTransform(1, 0, 0, 1, 0, 0); gf.globalCompositeOperation = 'source-over'; gf.globalAlpha = 1;
    const bg = gf.createRadialGradient(F.width * .5, F.height * .42, 8, F.width * .5, F.height * .42, Math.max(F.width, F.height) * .75);
    if (light) { bg.addColorStop(0, '#f6f7f9'); bg.addColorStop(1, '#e7e9ed'); } else { bg.addColorStop(0, '#051317'); bg.addColorStop(1, '#010405'); }
    gf.fillStyle = bg; gf.fillRect(0, 0, F.width, F.height);
    gf.globalCompositeOperation = ADD; gf.imageSmoothingEnabled = true; gf.imageSmoothingQuality = 'high';
    if (!light) { gf.globalAlpha = .34; gf.drawImage(B, 0, 0, F.width, F.height); }   // the haze is light on black: only for the dark look
    gf.setTransform(FS, 0, 0, FS, 0, 0); gf.globalAlpha = light ? .42 : .88;
    if (!off.includes('neurons')) for (const n of neurons) paintNeuron(gf, n, true);
    if (!off.includes('cells')) for (const k of cells) paint(gf, k, true);
    for (const s of specks) blob(gf, s.x, s.y, s.r * 2.2, '70,255,140', s.a);
    // 3. noise: photons arrive at random, and the camera adds its own; a new pattern about twenty times a second
    if (clock - noiseAt > .05 || noiseAt < 0) { noiseAt = clock; ni = Math.floor(R(0, 3)); nx = Math.floor(R(0, 256)); ny = Math.floor(R(0, 256)); }
    gf.setTransform(1, 0, 0, 1, 0, 0);
    if (!off.includes('noise')) {
    gf.globalCompositeOperation = 'overlay'; gf.globalAlpha = light ? .22 : .46; spread(gf, shot[ni], nx, ny);
    if (!light) { gf.globalCompositeOperation = 'lighter'; gf.globalAlpha = .13; spread(gf, dark[ni], ny, nx); }
    }

    // 4. the screen: only the overlay is drawn at full resolution, on a canvas that is otherwise empty
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.globalCompositeOperation = 'source-over'; g.globalAlpha = 1;
    g.clearRect(0, 0, W, H);
    // 5. the analysis overlay, sharp
    for (const k of cells) mark(k);
    let axon = 0;
    for (const n of neurons) {
      const len = arborLength(n); axon += len;
      if (len > 50 && n.state === 'grow') label(n.x + n.r + 12, n.y - n.r - 10, 'ARBOR  ' + Math.round(len * .52).toLocaleString() + ' µm  ·  ' + n.arbor.filter(b => b.growing).length + ' tips', `rgba(${INK.arbor},1)`, clamp(n.fade, 0, 1));
    }
    g.strokeStyle = `rgba(${INK.corner},.6)`; g.lineWidth = 1.6; const m = 12, L = 18;
    for (const [x, y, sx, sy] of [[m, m, 1, 1], [W - m, m, -1, 1], [m, H - m, 1, -1], [W - m, H - m, -1, -1]]) {
      g.beginPath(); g.moveTo(x, y + L * sy); g.lineTo(x, y); g.lineTo(x + L * sx, y); g.stroke();
    }
    if (clock - hudAt > .5 || hudAt < 0) {
      hudAt = clock;
      const mins = Math.floor(clock * 12);
      $('t').textContent = String(Math.floor(mins / 60)).padStart(2, '0') + ':' + String(mins % 60).padStart(2, '0');
      $('n').textContent = cells.filter(k => k.state !== 'dying').length;
      $('r').textContent = ruptures; $('d').textContent = divisions; $('x').textContent = deaths;
      $('a').textContent = Math.round(axon * .52).toLocaleString();
    }
  }
  requestAnimationFrame(frame);
  // for measuring the cost of a frame: bench(60) -> ms per frame
  window.bench = (n, read) => { benching = true; const t0 = performance.now();
    for (let i = 0; i < n; i++) { frame(last + 16); if (read === 'screen') g.getImageData(0, 0, 1, 1); if (read === 'camera') gf.getImageData(0, 0, 1, 1); }
    benching = false; requestAnimationFrame(frame); return (performance.now() - t0) / n; };
})();
</script>
</body></html>
"""
