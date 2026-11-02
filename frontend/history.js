/* MindPulse: saved check-ins (per browser) and live community statistics from MongoDB.
   Depends on script.js, which exposes window.MP. Everything is built with textContent, never innerHTML. */
(function () {
  "use strict";
  const { h, api } = window.MP;
  const $ = (id) => document.getElementById(id);

  const CAUSE = { sleep: "Sleep", screen_time: "Screen time", stress: "Perceived stress", activity: "Physical activity", workload: "Study workload", phone_checking: "Phone checking" };
  const causeName = (k) => CAUSE[k] || (k ? String(k).replace(/_/g, " ") : "None flagged");
  const MODE = { support: "Needs support", balance: "Needs balance", maintain: "Keep it up" };
  const fmtDate = (s) => { const d = new Date(String(s).replace(" ", "T") + "Z"); return isNaN(d) ? String(s || "") : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); };
  const num = (v, d = 1) => (typeof v === "number" && isFinite(v) ? v.toFixed(d) : "n/a");

  let records = [];

  /* ---------- history ---------- */
  function setStatus(text, warn) {
    $("history-status").textContent = text;
    const note = $("history-note");
    note.hidden = !warn;
    note.textContent = warn || "";
  }

  function emptyRow(text) {
    $("history-body").replaceChildren(h("tr", null, h("td", { colspan: "5", class: "empty", text })));
  }

  function profileText(r) {
    const i = r.inputs || {};
    const bits = [i.age != null ? `${i.age} yrs` : null, i.gender, i.country].filter(Boolean);
    return bits.join(" · ") || "Profile not stored";
  }

  function causeOf(r) {
    const k = r.primary_root_cause || null;
    if (k) return causeName(k);
    if (r.guidance) return "None flagged";
    return r.legacy_root_cause ? String(r.legacy_root_cause) : "Not analysed";
  }

  function row(r) {
    const level = window.MP.levelClass(r.level);
    const view = h("button", { class: "btn ghost small", type: "button", text: "View", "aria-label": `View saved report from ${fmtDate(r.created_at)}`, onclick: () => openRecord(r.id) });
    const del = h("button", { class: "btn ghost small danger", type: "button", text: "Delete", "aria-label": `Delete saved report from ${fmtDate(r.created_at)}`, onclick: () => removeRecord(r.id) });
    return h("tr", null,
      h("td", { text: fmtDate(r.created_at) }),
      h("td", { text: profileText(r) }),
      h("td", { class: "score-cell" }, h("strong", { text: num(r.predicted_score) }), h("span", { class: "level-pill " + level, text: r.level || "" })),
      h("td", { text: causeOf(r) }),
      h("td", null, h("div", { class: "row-actions" }, view, del)));
  }

  async function loadHistory() {
    let res;
    try { res = await api("/history?limit=100"); }
    catch (_) { records = []; setStatus("Could not reach the server.", "The API is not reachable. Start it with: uvicorn api.main:app --reload"); emptyRow("Nothing to show while the server is offline."); return; }
    if (res.status === 503) {
      records = [];
      setStatus("Database offline", (res.body && res.body.detail) || "MongoDB is not reachable, so history cannot be loaded.");
      emptyRow("Start MongoDB and press Refresh.");
      return;
    }
    if (res.status === 401) { records = []; setStatus("Sign in to view your private history."); emptyRow("Your saved check-ins will appear here after you sign in."); return; }
    if (!res.ok || !res.body) { setStatus("Could not load history.", "The server returned an unexpected response."); emptyRow("Try again in a moment."); return; }
    records = res.body.records || [];
    const scope = res.body.scope === "all" ? "all users" : "this browser";
    setStatus(records.length ? `${records.length} saved check-in${records.length === 1 ? "" : "s"} for ${scope}, newest first.` : `No check-ins saved yet for ${scope}.`);
    if (!records.length) { emptyRow("Run an assessment above and it will appear here."); return; }
    $("history-body").replaceChildren(...records.map(row));
  }

  async function openRecord(id) {
    const dlg = $("record-dialog"), body = $("dialog-body");
    body.replaceChildren(h("p", { class: "empty", text: "Loading saved report…" }));
    if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
    let res;
    try { res = await api("/history/" + encodeURIComponent(id)); } catch (_) { res = null; }
    if (!res || !res.ok) { body.replaceChildren(h("p", { class: "empty", text: res && res.status === 404 ? "This record no longer exists." : "Could not load this record." })); return; }
    const r = res.body;
    $("dialog-title").textContent = `Saved report · ${fmtDate(r.created_at)}`;
    const wrap = h("div", { class: "report" });
    body.replaceChildren(wrap);
    window.MP.renderReport(wrap, {
      score: r.predicted_score, level: r.level, guidance: r.guidance || null,
      notes: r.notes || [], components: (r.result || {}).component_predictions, explanations: r.explanations || [],
    });
  }

  async function removeRecord(id) {
    if (!window.confirm("Delete this saved check-in permanently?")) return;
    const res = await api("/history/" + encodeURIComponent(id), { method: "DELETE" }).catch(() => null);
    if (!res || !res.ok) { setStatus($("history-status").textContent, "Could not delete that record. Please try again."); return; }
    window.dispatchEvent(new Event("prediction-done"));  // refreshes history, stats and status pills
  }

  async function clearAll() {
    if (!records.length) return;
    if (!window.confirm(`Delete all ${records.length} saved check-ins for this browser? This cannot be undone.`)) return;
    const res = await api("/history?confirm=true", { method: "DELETE" }).catch(() => null);
    if (!res || !res.ok) { setStatus($("history-status").textContent, "Could not clear history. Please try again."); return; }
    window.dispatchEvent(new Event("prediction-done"));  // refreshes history, stats and status pills
  }

  /* ---------- CSV export (values starting with = + - @ are neutralised for spreadsheet safety) ---------- */
  function csvCell(v) {
    let s = v == null ? "" : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function exportCsv() {
    if (!records.length) { setStatus($("history-status").textContent, "There is nothing to export yet."); return; }
    const head = ["saved_at_utc", "age", "gender", "country", "academic_level", "platform", "purpose", "daily_usage_hours", "daily_unlocks", "study_hours", "physical_activity_hours", "sleep_hours", "stress_level", "predicted_score", "band", "guidance_mode", "pressure_index", "main_root_cause", "top_recommendation"];
    const lines = [head.join(",")];
    for (const r of records) {
      const i = r.inputs || {}, g = r.guidance || {}, rec = (g.recommendations || [])[0];
      lines.push([r.created_at, i.age, i.gender, i.country, i.academic_level, i.most_used_platform, i.purpose_of_use, i.avg_daily_usage_hours, i.daily_unlocks, i.study_hours,
        i.physical_activity_hours, i.sleep_hours_per_night, i.stress_level, r.predicted_score, r.level, g.mode || "", g.pressure_index != null ? g.pressure_index : "", causeOf(r), rec ? rec.first_step : ""].map(csvCell).join(","));
    }
    const url = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const a = h("a", { href: url, download: "mindpulse_history.csv" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /* ---------- your progress (built only from the signed-in user's own check-ins) ---------- */
  const SVG = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs, ...kids) => { const e = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v); kids.forEach((k2) => e.append(k2)); return e; };
  const TARGETS = [
    { key: "sleep_hours_per_night", label: "Sleep", unit: "h", min: 0, max: 10, ok: (v) => v >= 7 && v <= 9.5, target: "7-9 h" },
    { key: "avg_daily_usage_hours", label: "Screen time", unit: "h", min: 0, max: 12, ok: (v) => v <= 4, target: "4 h or less" },
    { key: "physical_activity_hours", label: "Physical activity", unit: "h", min: 0, max: 2, ok: (v) => v >= 1, target: "about 1 h" },
    { key: "study_hours", label: "Study time", unit: "h", min: 0, max: 12, ok: (v) => v <= 5, target: "5 h or less" },
    { key: "daily_unlocks", label: "Phone unlocks", unit: "", min: 0, max: 300, ok: (v) => v <= 150, target: "150 or fewer" },
  ];

  function trendChart(list) {                       // list is oldest -> newest
    const w = 640, ht = 220, L = 34, R = 26, T = 14, B = 34, iw = w - L - R, ih = ht - T - B;
    const x = (i) => L + (list.length === 1 ? iw / 2 : (i / (list.length - 1)) * iw), y = (v) => T + (1 - v / 10) * ih;
    const root = svg("svg", { viewBox: `0 0 ${w} ${ht}`, class: "trend-svg", role: "img", "aria-label": `Your last ${list.length} wellness scores` });
    const defs = svg("defs", null, svg("linearGradient", { id: "tg", x1: "0", y1: "0", x2: "1", y2: "0" }, svg("stop", { offset: "0", "stop-color": "#6fe3ff" }), svg("stop", { offset: "1", "stop-color": "#7c8cff" })),
      svg("linearGradient", { id: "ta", x1: "0", y1: "0", x2: "0", y2: "1" }, svg("stop", { offset: "0", "stop-color": "#6fe3ff", "stop-opacity": ".28" }), svg("stop", { offset: "1", "stop-color": "#6fe3ff", "stop-opacity": "0" })));
    root.append(defs);
    root.append(svg("rect", { x: L, y: y(10), width: iw, height: y(7) - y(10), fill: "rgba(92,240,200,.07)" }), svg("rect", { x: L, y: y(7), width: iw, height: y(5) - y(7), fill: "rgba(255,194,107,.06)" }), svg("rect", { x: L, y: y(5), width: iw, height: y(0) - y(5), fill: "rgba(255,122,133,.05)" }));
    [0, 2.5, 5, 7, 10].forEach((v) => { root.append(svg("line", { x1: L, x2: w - R, y1: y(v), y2: y(v), stroke: "rgba(150,190,255,.12)", "stroke-dasharray": "3 5" })); const t = svg("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end", fill: "#7f93ad", "font-size": "11" }); t.textContent = v; root.append(t); });
    const d = list.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(r.score).toFixed(1)}`).join(" ");
    if (list.length > 1) { root.append(svg("path", { d: `${d} L${x(list.length - 1).toFixed(1)} ${y(0)} L${x(0).toFixed(1)} ${y(0)} Z`, fill: "url(#ta)" })); root.append(svg("path", { d, fill: "none", stroke: "url(#tg)", "stroke-width": "3", "stroke-linecap": "round", "stroke-linejoin": "round", class: "trend-line" })); }
    list.forEach((r, i) => {
      const c = svg("circle", { cx: x(i), cy: y(r.score), r: "5", fill: "#0a1322", stroke: r.score >= 7 ? "#5cf0c8" : r.score >= 5 ? "#ffc26b" : "#ff7a85", "stroke-width": "2.5", class: "trend-dot" });
      const tt = svg("title"); tt.textContent = `${r.score.toFixed(1)} / 10 · ${r.when}`; c.append(tt); root.append(c);
      if (list.length <= 8 || i === 0 || i === list.length - 1 || i % 2 === 0) { const t = svg("text", { x: x(i), y: ht - 12, "text-anchor": "middle", fill: "#7f93ad", "font-size": "11" }); t.textContent = r.short; root.append(t); }
    });
    return root;
  }

  function habitSnapshot(latest) {
    const i = latest.inputs || {};
    return h("div", { class: "snap" }, ...TARGETS.filter((t) => Number.isFinite(Number(i[t.key]))).map((t) => {
      const v = Number(i[t.key]), good = t.ok(v), pct = Math.max(4, Math.min(100, ((v - t.min) / (t.max - t.min)) * 100));
      const fill = h("i", { class: good ? "ok" : "warn" });
      requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = pct + "%"; }));
      return h("div", { class: "snap-row" }, h("span", { class: "snap-label", text: t.label }), h("div", { class: "bar" }, fill),
        h("b", { text: `${+v.toFixed(1)}${t.unit ? " " + t.unit : ""}` }), h("em", { class: good ? "ok" : "warn", text: good ? "On target" : `Target: ${t.target}` }));
    }));
  }

  async function loadCommunity() {
    const box = $("community-body");
    let res;
    try { res = await api("/history?limit=100"); } catch (_) { res = null; }
    if (!res) { box.replaceChildren(h("p", { class: "empty", text: "We could not reach the server. Your progress will appear when it is back." })); return; }
    if (res.status === 401) { box.replaceChildren(h("p", { class: "empty", text: "Sign in to see your own progress." })); return; }
    if (res.status === 503) { box.replaceChildren(h("p", { class: "empty", text: "Your history is temporarily unavailable. Please try again in a moment." })); return; }
    if (!res.ok || !res.body) { box.replaceChildren(h("p", { class: "empty", text: "Could not load your progress." })); return; }
    const recs = (res.body.records || []).filter((r) => Number.isFinite(Number(r.predicted_score)));
    if (!recs.length) {
      box.replaceChildren(h("div", { class: "progress-empty" }, h("strong", { text: "Your progress starts with one check-in" }),
        h("p", { text: "Fill in the check-in above. Afterwards this space shows your score trend, how your habits compare with healthy targets, and what to work on next." }),
        h("a", { class: "btn primary small", href: "#assessment", text: "Start a check-in" })));
      return;
    }
    const asc = recs.slice().reverse().slice(-12).map((r) => {
      const dt = new Date(String(r.created_at).replace(" ", "T") + "Z");
      return { score: Number(r.predicted_score), when: fmtDate(r.created_at), short: isNaN(dt) ? "" : dt.toLocaleDateString(undefined, { day: "numeric", month: "short" }) };
    });
    const scores = recs.map((r) => Number(r.predicted_score));
    const avg = scores.reduce((a, c) => a + c, 0) / scores.length, best = Math.max(...scores);
    const delta = scores.length > 1 ? scores[0] - scores[1] : null;
    const stat = (v, l, cls) => h("div", null, h("strong", { class: cls || "", text: v }), h("span", { text: l }));
    const deltaText = delta == null ? "First check-in" : Math.abs(delta) < 0.05 ? "Steady" : `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`;
    const parts = [h("div", { class: "stat-grid four" }, stat(String(res.body.count ?? recs.length), "check-ins saved"), stat(avg.toFixed(1), "your average score"), stat(best.toFixed(1), "your best score"),
      stat(deltaText, delta == null ? "change since last time" : "change since the check-in before", delta == null ? "" : delta > 0.05 ? "up" : delta < -0.05 ? "down" : ""))];

    const grid = h("div", { class: "progress-grid" });
    const left = h("div", null, h("h3", { class: "mini-title", text: "Score trend" }));
    if (asc.length > 1) left.append(h("div", { class: "trend-wrap" }, trendChart(asc)), h("p", { class: "legend", text: "Green: healthy (7+). Amber: moderate (5-6.9). Red: needs support (under 5)." }));
    else left.append(h("p", { class: "sub", text: "Do one more check-in on another day to see your trend line." }));
    const right = h("div", null, h("h3", { class: "mini-title", text: "Latest habits vs healthy targets" }), habitSnapshot(recs[0]));
    grid.append(left, right); parts.push(grid);

    const counts = {};
    recs.forEach((r) => { if (r.primary_root_cause) counts[r.primary_root_cause] = (counts[r.primary_root_cause] || 0) + 1; });
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    const last = new Date(String(recs[0].created_at).replace(" ", "T") + "Z"), days = isNaN(last) ? null : Math.floor((Date.now() - last) / 86400000);
    const lines = [];
    if (top) lines.push(`${causeName(top[0])} is your most common main driver (${top[1]} of ${recs.length} check-in${recs.length === 1 ? "" : "s"}). A small daily change there will move your score the most.`);
    if (delta != null && delta > 0.05) lines.push("Your latest score is higher than the one before. Whatever you changed is working, so keep it going.");
    else if (delta != null && delta < -0.05) lines.push("Your latest score dipped a little. Check your sleep and screen time first, then follow Priority 1 in your plan.");
    if (days != null) lines.push(days >= 14 ? `It has been ${days} days since your last check-in. A new one will show whether your plan is helping.` : `Your last check-in was ${days === 0 ? "today" : days + " day" + (days === 1 ? "" : "s") + " ago"}. A good rhythm is one check-in every two weeks.`);
    parts.push(h("div", { class: "coach" }, h("strong", { text: "What this means for you" }), h("ul", null, ...lines.map((t) => h("li", { text: t })))));
    box.replaceChildren(...parts);
  }

  /* ---------- wiring ---------- */
  $("history-refresh").addEventListener("click", loadHistory);
  $("history-export").addEventListener("click", exportCsv);
  $("history-clear").addEventListener("click", clearAll);
  $("community-refresh").addEventListener("click", loadCommunity);
  $("dialog-close").addEventListener("click", () => $("record-dialog").close());
  $("record-dialog").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  window.addEventListener("prediction-done", () => { loadHistory(); loadCommunity(); if (window.MP && window.MP.refreshStatus) window.MP.refreshStatus(); });

  window.addEventListener("auth-ready", () => { loadHistory(); loadCommunity(); });
  window.addEventListener("auth-logged-out", () => {
    records = [];
    setStatus("Sign in to view your private history.", "Your previous account data has been cleared from this page.");
    emptyRow("Your saved check-ins will appear here after you sign in.");
  });
  loadCommunity();
})();
