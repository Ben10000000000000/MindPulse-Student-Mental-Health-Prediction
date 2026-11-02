/* MindPulse sign-in atmosphere + toast messages.
   - window.MPToast.show({type, title, text, ms}) shows a message (used for OTP / welcome / welcome back).
   - A 3D particle sphere on the sign-in canvas, a mouse-tilt on the card and a parallax orbit. All stop when the auth screen is hidden
     and are disabled for people who prefer reduced motion. Everything is built with textContent. */
(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (id) => document.getElementById(id);

  /* ---------- toast ---------- */
  const ICON = { success: "✓", info: "✉", welcome: "👋", error: "!" };
  function show({ type = "info", title = "", text = "", ms = 6000 } = {}) {
    const root = $("toast-root"); if (!root) return;
    const t = document.createElement("div"); t.className = "toast toast-" + type; t.setAttribute("role", type === "error" ? "alert" : "status");
    const ic = document.createElement("span"); ic.className = "toast-icon"; ic.textContent = ICON[type] || "•";
    const body = document.createElement("div"); body.className = "toast-body";
    const h = document.createElement("strong"); h.textContent = title;
    const p = document.createElement("p"); p.textContent = text;
    const x = document.createElement("button"); x.type = "button"; x.className = "toast-x"; x.setAttribute("aria-label", "Dismiss message"); x.textContent = "×";
    const bar = document.createElement("i"); bar.className = "toast-bar"; bar.style.animationDuration = ms + "ms";
    body.append(h, p); t.append(ic, body, x, bar); root.append(t);
    while (root.children.length > 3) root.firstElementChild.remove();
    const close = () => { t.classList.add("toast-out"); setTimeout(() => t.remove(), 380); };
    x.addEventListener("click", close);
    const timer = setTimeout(close, ms);
    t.addEventListener("pointerenter", () => { clearTimeout(t._t); t.classList.add("toast-hold"); });
    t._t = timer;
    t.addEventListener("pointerleave", () => { t.classList.remove("toast-hold"); t._t = setTimeout(close, 2500); });
  }
  window.MPToast = { show };

  /* ---------- 3D particle sphere on the auth canvas ---------- */
  const screen = $("auth-screen"), cv = $("auth-canvas");
  if (!screen || !cv || reduce) return;
  const ctx = cv.getContext("2d");
  let W = 0, H = 0, dpr = 1, mx = 0, my = 0, tx = 0, ty = 0, raf = 0, running = false, t0 = performance.now();
  const N = 150, pts = [];
  for (let i = 0; i < N; i++) {                       // fibonacci sphere
    const k = i + .5, phi = Math.acos(1 - 2 * k / N), th = Math.PI * (1 + Math.sqrt(5)) * k;
    pts.push([Math.sin(phi) * Math.cos(th), Math.cos(phi), Math.sin(phi) * Math.sin(th)]);
  }
  const dust = Array.from({ length: 60 }, () => ({ x: Math.random(), y: Math.random(), z: Math.random(), s: Math.random() * 1.4 + .3 }));
  function size() {
    dpr = Math.min(window.devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + "px"; cv.style.height = H + "px"; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function frame(now) {
    if (!running) return;
    const t = (now - t0) / 1000; tx += (mx - tx) * .05; ty += (my - ty) * .05;
    ctx.clearRect(0, 0, W, H);
    const wide = W > 900, cx = wide ? W * .28 : W * .5, cy = wide ? H * .56 : H * .2, R = Math.min(W, H) * (wide ? .26 : .16);
    const ry = t * .22 + tx * .8, rx = .35 + ty * .5, cyaw = Math.cos(ry), syaw = Math.sin(ry), cp = Math.cos(rx), sp = Math.sin(rx);
    const proj = pts.map(([x, y, z]) => {
      const x1 = x * cyaw + z * syaw, z1 = -x * syaw + z * cyaw, y1 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
      const f = 1 / (1.9 - z2 * .6); return [cx + x1 * R * f * 1.5, cy + y1 * R * f * 1.5, z2];
    });
    ctx.lineWidth = 1;
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const dx = proj[i][0] - proj[j][0], dy = proj[i][1] - proj[j][1], d = dx * dx + dy * dy;
      if (d < 1500) { const a = (1 - d / 1500) * .22 * ((proj[i][2] + proj[j][2] + 2) / 4 + .2); ctx.strokeStyle = `rgba(111,227,255,${a})`; ctx.beginPath(); ctx.moveTo(proj[i][0], proj[i][1]); ctx.lineTo(proj[j][0], proj[j][1]); ctx.stroke(); }
    }
    for (const [x, y, z] of proj) {
      const a = .25 + (z + 1) * .35; ctx.fillStyle = z > 0 ? `rgba(92,240,200,${a})` : `rgba(124,140,255,${a * .8})`;
      ctx.beginPath(); ctx.arc(x, y, 1 + (z + 1) * .9, 0, 6.283); ctx.fill();
    }
    for (const d of dust) {                           // drifting dust with depth parallax
      const x = ((d.x + t * .005 * (d.z + .3)) % 1) * W - tx * 30 * d.z, y = (d.y + Math.sin(t * .3 + d.x * 9) * .01) * H - ty * 30 * d.z;
      ctx.fillStyle = `rgba(190,225,255,${.12 + d.z * .22})`; ctx.fillRect(x, y, d.s, d.s);
    }
    raf = requestAnimationFrame(frame);
  }
  function start() { if (running || screen.classList.contains("hidden-auth")) return; running = true; size(); raf = requestAnimationFrame(frame); }
  function stop() { running = false; cancelAnimationFrame(raf); }
  new MutationObserver(() => (screen.classList.contains("hidden-auth") ? stop() : start())).observe(screen, { attributes: true, attributeFilter: ["class"] });
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  addEventListener("resize", () => { if (running) size(); });

  /* ---------- tilt + parallax ---------- */
  const wrap = $("auth-card-wrap"), orbit = $("orbit-stage");
  screen.addEventListener("pointermove", (e) => {
    mx = (e.clientX / innerWidth - .5) * 2; my = (e.clientY / innerHeight - .5) * 2;
    if (wrap && innerWidth > 760) wrap.style.setProperty("--tilt", `rotateX(${(-my * 4).toFixed(2)}deg) rotateY(${(mx * 5).toFixed(2)}deg)`);
    if (orbit) orbit.style.transform = `rotateX(${(-my * 10).toFixed(1)}deg) rotateY(${(mx * 14).toFixed(1)}deg)`;
  });
  screen.addEventListener("pointerleave", () => { mx = my = 0; if (wrap) wrap.style.setProperty("--tilt", "none"); if (orbit) orbit.style.transform = ""; });
  start();
})();
