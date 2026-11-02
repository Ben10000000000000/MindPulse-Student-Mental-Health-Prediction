/* MindPulse visual layer: constellation background, heartbeat trace and the hero orb.
   Motion is paused when the tab is hidden or the orb is off-screen, and drawn once when the user prefers reduced motion. */
(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const MOODS = { idle: [111, 227, 255], support: [255, 122, 133], balance: [255, 194, 107], maintain: [92, 240, 200] };
  const mood = MOODS.idle.slice();
  let target = MOODS.idle.slice();
  const lerp = (a, b, t) => a + (b - a) * t;
  const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
  const mouse = { x: -999, y: -999, nx: 0, ny: 0 };

  /* ---------------- background field ---------------- */
  const bg = document.getElementById("bg");
  const bx = bg && bg.getContext("2d");
  let W = 0, H = 0, parts = [];

  function sizeBg() {
    if (!bx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    W = window.innerWidth; H = window.innerHeight;
    bg.width = Math.round(W * dpr); bg.height = Math.round(H * dpr);
    bx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.max(26, Math.min(88, Math.round((W * H) / 23000)));
    parts = Array.from({ length: n }, () => ({
      x: Math.random() * W, y: Math.random() * H, r: Math.random() * 1.3 + 0.5,
      vx: (Math.random() - 0.5) * 0.22, vy: (Math.random() - 0.5) * 0.22,
    }));
  }

  const g = (u, c, a, w) => a * Math.exp(-(((u - c) / w) ** 2));
  const beat = (u) => g(u, 0.18, 0.12, 0.035) + g(u, 0.3, -0.12, 0.012) + g(u, 0.335, 1, 0.009) + g(u, 0.365, -0.28, 0.012) + g(u, 0.56, 0.24, 0.05);

  function drawBg(t) {
    if (!bx) return;
    bx.clearRect(0, 0, W, H);
    for (let i = 0; i < 3; i++) mood[i] = lerp(mood[i], target[i], 0.04);
    const sy = window.scrollY || 0;

    for (const p of parts) {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > W) p.vx *= -1;
      if (p.y < 0 || p.y > H) p.vy *= -1;
      const dx = p.x - mouse.x, dy = p.y - mouse.y, d2 = dx * dx + dy * dy;
      if (d2 < 19600 && d2 > 0) { const d = Math.sqrt(d2), f = (1 - d / 140) * 0.7; p.x += (dx / d) * f; p.y += (dy / d) * f; }
      p.dy = (((p.y - sy * 0.05 * p.r) % H) + H) % H;
    }
    bx.lineWidth = 1;
    for (let i = 0; i < parts.length; i++) {
      const a = parts[i];
      for (let j = i + 1; j < parts.length; j++) {
        const b = parts[j], dx = a.x - b.x, dy = a.dy - b.dy, d2 = dx * dx + dy * dy;
        if (d2 < 16900) {
          bx.strokeStyle = rgba(mood, (1 - Math.sqrt(d2) / 130) * 0.16);
          bx.beginPath(); bx.moveTo(a.x, a.dy); bx.lineTo(b.x, b.dy); bx.stroke();
        }
      }
    }
    bx.fillStyle = rgba(mood, 0.55);
    for (const p of parts) { bx.beginPath(); bx.arc(p.x, p.dy, p.r, 0, 6.2832); bx.fill(); }

    /* heartbeat trace along the lower part of the viewport */
    const base = H * 0.9, amp = Math.min(46, H * 0.06), cycles = Math.max(1.6, W / 620), phase = (t || 0) * 0.00011;
    const grad = bx.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0, rgba(mood, 0)); grad.addColorStop(0.25, rgba(mood, 0.5)); grad.addColorStop(0.75, rgba(mood, 0.5)); grad.addColorStop(1, rgba(mood, 0));
    const path = new Path2D();
    for (let x = 0; x <= W; x += 3) {
      let u = (x / W) * cycles - phase; u -= Math.floor(u);
      const y = base - beat(u) * amp;
      x === 0 ? path.moveTo(x, y) : path.lineTo(x, y);
    }
    bx.strokeStyle = grad; bx.lineJoin = "round";
    bx.globalAlpha = 0.16; bx.lineWidth = 6; bx.stroke(path);
    bx.globalAlpha = 0.7; bx.lineWidth = 1.4; bx.stroke(path);
    bx.globalAlpha = 1;
  }

  /* ---------------- hero orb ---------------- */
  const orb = document.getElementById("orb");
  const ox = orb && orb.getContext("2d");
  let S = 0, orbVisible = true, tiltX = 0.35, tiltY = 0;
  const N = 340, sphere = [];
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = Math.PI * (3 - Math.sqrt(5)) * i;
    sphere.push([Math.cos(th) * r, y, Math.sin(th) * r]);
  }
  const NODES = [
    { label: "Sleep", incl: 0.5, speed: 0.19, off: 0.0 }, { label: "Screen time", incl: -0.35, speed: 0.15, off: 1.7 },
    { label: "Stress", incl: 1.0, speed: 0.13, off: 3.1 }, { label: "Activity", incl: -0.9, speed: 0.17, off: 4.4 },
    { label: "Study", incl: 0.05, speed: 0.11, off: 5.5 },
  ];

  function sizeOrb() {
    if (!ox) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), r = orb.getBoundingClientRect();
    S = Math.max(220, r.width);
    orb.width = Math.round(S * dpr); orb.height = Math.round(S * dpr);
    ox.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function project(x, y, z, ry, rx, R, cx, cy) {
    const cY = Math.cos(ry), sY = Math.sin(ry);
    let x1 = x * cY + z * sY, z1 = -x * sY + z * cY;
    const cX = Math.cos(rx), sX = Math.sin(rx);
    const y1 = y * cX - z1 * sX, z2 = y * sX + z1 * cX;
    const s = 3 / (3 - z2 * 0.6);
    return [cx + x1 * R * s, cy + y1 * R * s, z2];
  }

  /* a point on a tilted circular orbit around the sphere */
  const orbitPoint = (th, incl) => [Math.cos(th) * 1.42, Math.sin(th) * 1.42 * Math.sin(incl), Math.sin(th) * 1.42 * Math.cos(incl)];

  function drawOrb(t) {
    if (!ox) return;
    const cx = S / 2, cy = S / 2, R = S * 0.33, time = (t || 0) * 0.001;
    ox.clearRect(0, 0, S, S);
    tiltX += (0.35 + mouse.ny * 0.28 - tiltX) * 0.04;
    tiltY += (mouse.nx * 0.5 - tiltY) * 0.04;
    const ry = time * 0.16 + tiltY;

    const glow = ox.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.55);
    glow.addColorStop(0, rgba(mood, 0.2)); glow.addColorStop(0.55, rgba(mood, 0.06)); glow.addColorStop(1, rgba(mood, 0));
    ox.fillStyle = glow; ox.fillRect(0, 0, S, S);

    const cycle = (time % 3.2) / 3.2;                      // pulse ripple
    ox.lineWidth = 1.2;
    ox.strokeStyle = rgba(mood, (1 - cycle) * 0.35);
    ox.beginPath(); ox.arc(cx, cy, R * (1.02 + cycle * 0.5), 0, 6.2832); ox.stroke();

    ox.lineWidth = 1;                                       // orbit paths
    NODES.forEach((n) => {
      ox.strokeStyle = rgba(mood, 0.1); ox.beginPath();
      for (let a = 0; a <= 64; a++) {
        const q = orbitPoint((a / 64) * 6.2832, n.incl), p = project(q[0], q[1], q[2], ry * 0.3, tiltX, R, cx, cy);
        a === 0 ? ox.moveTo(p[0], p[1]) : ox.lineTo(p[0], p[1]);
      }
      ox.stroke();
    });

    for (const [x, y, z] of sphere) {                       // the sphere of points
      const p = project(x, y, z, ry, tiltX, R, cx, cy), depth = (p[2] + 1) / 2;
      const wave = 0.5 + 0.5 * Math.sin(time * 1.6 + y * 5 + x * 3);
      ox.fillStyle = rgba(mood, 0.14 + depth * 0.66 * (0.65 + 0.35 * wave));
      ox.beginPath(); ox.arc(p[0], p[1], 0.7 + depth * 1.5, 0, 6.2832); ox.fill();
    }

    ox.font = "600 12px Manrope, system-ui, sans-serif"; ox.textBaseline = "middle";
    NODES.forEach((n) => {                                  // habit satellites
      const q = orbitPoint(time * n.speed + n.off, n.incl);
      const p = project(q[0], q[1], q[2], ry * 0.3, tiltX, R, cx, cy), depth = (p[2] + 1.5) / 3;
      ox.fillStyle = rgba(mood, 0.25 + depth * 0.75);
      ox.beginPath(); ox.arc(p[0], p[1], 3.2 + depth * 2.4, 0, 6.2832); ox.fill();
      ox.fillStyle = `rgba(233,241,250,${0.35 + depth * 0.6})`;
      ox.fillText(n.label, p[0] + 11, p[1]);
    });
  }

  /* ---------------- loop ---------------- */
  let raf = 0;
  function frame(t) {
    drawBg(t);
    if (orbVisible) drawOrb(t);
    raf = requestAnimationFrame(frame);
  }
  function start() {
    if (reduce) { drawBg(0); drawOrb(0); return; }
    if (!raf) raf = requestAnimationFrame(frame);
  }
  function stop() { cancelAnimationFrame(raf); raf = 0; }

  window.addEventListener("pointermove", (e) => {
    mouse.x = e.clientX; mouse.y = e.clientY;
    mouse.nx = e.clientX / window.innerWidth - 0.5; mouse.ny = e.clientY / window.innerHeight - 0.5;
  }, { passive: true });
  window.addEventListener("pointerleave", () => { mouse.x = mouse.y = -999; });
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { sizeBg(); sizeOrb(); if (reduce) { drawBg(0); drawOrb(0); } }, 150); });
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  if (orb && "IntersectionObserver" in window) new IntersectionObserver((e) => { orbVisible = e[0].isIntersecting; }).observe(orb);

  window.MPFX = {
    /** mood: idle | support | balance | maintain. Optionally show the score in the orb. */
    setMood(name, scoreText) {
      target = (MOODS[name] || MOODS.idle).slice();
      document.body.dataset.mood = MOODS[name] ? name : "idle";
      const s = document.getElementById("orb-score"), c = document.getElementById("orb-caption");
      if (s) s.textContent = scoreText || "0–10";
      if (c) c.textContent = scoreText ? "your score" : "wellness score";
      if (reduce) { for (let i = 0; i < 3; i++) mood[i] = target[i]; drawBg(0); drawOrb(0); }
    },
  };

  sizeBg(); sizeOrb();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => reduce && drawOrb(0));
  start();
})();
