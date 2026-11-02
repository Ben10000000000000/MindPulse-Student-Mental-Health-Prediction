/* MindPulse front end: check-in form, result card and the root-cause report.
   All DOM is built with textContent (never innerHTML) so nothing typed by a user can inject markup. */
(() => {
  "use strict";

  /* ---------- helpers ---------- */
  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  /* API address: same origin when the site is served by FastAPI at /app, otherwise localhost:8000 */
  const API_BASE = window.API_BASE || (/^https?:$/.test(location.protocol) && location.pathname.startsWith("/app") ? location.origin : "http://127.0.0.1:8000");
  let memoryId = null;
  const CID = (() => {
    const make = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_-]/g, "");
    try {
      let id = localStorage.getItem("mindpulse_client_id");
      if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) { id = make(); localStorage.setItem("mindpulse_client_id", id); }
      return id;
    } catch (_) { return (memoryId = memoryId || make()); }
  })();

  async function api(path, opts = {}) {
    const token = (() => { try { return localStorage.getItem("mindpulse_access_token") || ""; } catch (_) { return ""; } })();
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    const r = await fetch(API_BASE + path, { ...opts, headers });
    let body = null;
    try { body = await r.json(); } catch (_) { /* empty body */ }
    if (r.status === 401) window.dispatchEvent(new Event("auth-expired"));
    return { ok: r.ok, status: r.status, body };
  }

  const FALLBACK = {
    genders: ["Female", "Male", "Other"],
    academic_levels: ["Early Childhood / Pre-primary", "Primary School", "Middle School / Lower Secondary", "High School / Upper Secondary", "Diploma / Vocational", "Undergraduate", "Postgraduate (Master's)", "Doctoral (PhD)", "Other"],
    employment_statuses: ["None (student only)", "Part-time job", "Internship", "Full-time job"],
    platforms: ["Facebook", "Instagram", "Snapchat", "Twitter", "YouTube", "TikTok", "LinkedIn", "LINE", "KakaoTalk", "VKontakte", "WhatsApp", "WeChat"],
    purposes: ["Communication", "Education", "Entertainment", "Networking", "News"],
    countries: ["Australia", "Bangladesh", "Brazil", "Canada", "China", "France", "Germany", "India", "Italy", "Japan", "Mexico", "Nepal", "Netherlands", "Nigeria", "Pakistan", "Philippines", "Russia", "Singapore", "South Korea", "Spain", "Sri Lanka", "Turkey", "UAE", "UK", "USA"],
    ranges: { age: [18, 24], avg_daily_usage_hours: [1, 8.8], daily_unlocks: [62, 273], study_hours: [0.3, 8.3], physical_activity_hours: [0, 4.1], sleep_hours_per_night: [3.6, 9.9] },
  };
  let RANGES = FALLBACK.ranges;

  /* ---------- form ---------- */
  const form = $("predict-form"), submitBtn = $("submit-btn");
  const NUMBER_FIELDS = { age: [5, 30, "Age"], avg_daily_usage_hours: [0, 24, "Screen time"], daily_unlocks: [0, 1000, "Phone unlocks"], study_hours: [0, 24, "Study time"], physical_activity_hours: [0, 24, "Physical activity"], sleep_hours_per_night: [0, 24, "Sleep"] };
  const TEXT_FIELDS = ["gender", "country", "academic_level", "employment_status", "most_used_platform", "purpose_of_use"];
  const INT_FIELDS = ["age", "daily_unlocks"];

  function collect() {
    const p = {};
    for (const k of Object.keys(NUMBER_FIELDS)) {
      const raw = $(k).value.trim();
      p[k] = raw === "" ? NaN : (INT_FIELDS.includes(k) ? parseInt(raw, 10) : parseFloat(raw));
    }
    for (const k of TEXT_FIELDS) p[k] = $(k).value.trim();
    p.stress_level = $("stress_level").value;
    return p;
  }

  const wrapper = (el) => el && el.closest(".field");
  function setError(el, msg) { const w = wrapper(el); if (!w) return false; w.classList.add("field-error"); w.querySelector(".error-msg").textContent = msg; return true; }
  function clearError(el) { const w = wrapper(el); if (!w) return; w.classList.remove("field-error"); w.querySelector(".error-msg").textContent = ""; }
  function clearAllErrors() { form.querySelectorAll(".field").forEach((w) => { w.classList.remove("field-error"); w.querySelector(".error-msg").textContent = ""; }); setFormError(""); }
  function setFormError(msg) { const e = $("form-error"); e.textContent = msg; e.hidden = !msg; }

  function validate(p) {
    const errs = [];
    for (const [k, [lo, hi, label]] of Object.entries(NUMBER_FIELDS)) {
      if (Number.isNaN(p[k])) errs.push([$(k), `${label} is required.`]);
      else if (p[k] < lo || p[k] > hi) errs.push([$(k), k === "age" ? "You can check mental analysis only between age 5 and 30, not less than 5 or greater than 30." : `Use a value from ${lo} to ${hi}.`]);
    }
    for (const k of TEXT_FIELDS) if (!p[k]) errs.push([$(k), "This field is required."]);
    if (!p.stress_level) errs.push([$("stress_level"), "Choose how stressed you feel."]);
    let formMsg = "";
    if (!errs.length) {
      const used = p.sleep_hours_per_night + p.study_hours + p.physical_activity_hours;
      if (used > 24) formMsg = `Sleep, study and activity add up to ${+used.toFixed(1)} h, more than the 24 h in a day. Please check these values.`;
      else if (p.avg_daily_usage_hours > 24 - p.sleep_hours_per_night) formMsg = `Screen time cannot be more than your waking hours (${+(24 - p.sleep_hours_per_night).toFixed(1)} h).`;
    }
    if (!formMsg && errs.some(([el]) => el && el.id === "age") && !Number.isNaN(p.age)) formMsg = "You can check mental analysis only between age 5 and 30, not less than 5 or greater than 30.";
    return { errs, formMsg };
  }

  function updateProgress() {
    const p = collect();
    const filled = Object.keys(NUMBER_FIELDS).filter((k) => !Number.isNaN(p[k])).length + TEXT_FIELDS.filter((k) => p[k]).length + (p.stress_level ? 1 : 0);
    const pct = Math.round((filled / 12) * 100);
    $("progress-bar").style.width = pct + "%";
    $("progress-text").textContent = pct + "% complete";
  }

  function setHint(id, text, warn) { const e = $(id); if (!e) return; e.textContent = text; e.classList.toggle("warn", !!warn); }
  function inRange(key, v) { const [lo, hi] = RANGES[key] || [-Infinity, Infinity]; return v >= lo && v <= hi; }

  function updateLive() {
    const p = collect(), ok = (v) => !Number.isNaN(v);
    if (ok(p.age)) setHint("hint-age", inRange("age", p.age) ? "Years" : `The model learned from ages ${RANGES.age[0]}–${RANGES.age[1]}, so this is approximate`, !inRange("age", p.age)); else setHint("hint-age", "Years");
    if (ok(p.sleep_hours_per_night)) {
      const s = p.sleep_hours_per_night;
      setHint("hint-sleep", s < 5 ? "Well below the 7–9 h most adults need" : s < 7 ? "Below the 7–9 h most adults need" : s <= 9 ? "In the healthy 7–9 h range" : "Above 9 h", s < 7 || s > 9);
      $("sleep-meter").style.width = Math.min(100, (s / 10) * 100) + "%";
      $("sleep-meter").style.background = s < 5 ? "var(--coral)" : s < 7 ? "var(--amber)" : "var(--mint)";
    } else { setHint("hint-sleep", "Most adults do best on 7–9 h"); $("sleep-meter").style.width = "0"; }
    if (ok(p.avg_daily_usage_hours)) {
      const v = p.avg_daily_usage_hours;
      setHint("hint-screen", v <= 4 ? "A balanced amount" : v <= 6 ? "Moderate to high" : "High screen time", v > 6);
      $("screen-meter").style.width = Math.min(100, (v / 12) * 100) + "%";
      $("screen-meter").style.background = v > 7 ? "var(--coral)" : v > 4 ? "var(--amber)" : "var(--ice)";
    } else { setHint("hint-screen", "Social media and phone use"); $("screen-meter").style.width = "0"; }
    setHint("hint-unlocks", ok(p.daily_unlocks) ? (p.daily_unlocks <= 150 ? "A calm checking pace" : "Frequent checking") : "A rough number is fine", ok(p.daily_unlocks) && p.daily_unlocks > 150);
    setHint("hint-study", ok(p.study_hours) && p.study_hours > 5 ? "A heavy study day" : "Classes and self-study", ok(p.study_hours) && p.study_hours > 5);
    setHint("hint-activity", ok(p.physical_activity_hours) ? (p.physical_activity_hours >= 1 ? "About an hour a day or more" : "Under an hour a day") : "Walking, sport, workouts");

    const sl = ok(p.sleep_hours_per_night) ? p.sleep_hours_per_night : 0, st = ok(p.study_hours) ? p.study_hours : 0, mv = ok(p.physical_activity_hours) ? p.physical_activity_hours : 0;
    const used = sl + st + mv, box = $("day-budget");
    $("seg-sleep").style.width = Math.min(100, (sl / 24) * 100) + "%";
    $("seg-study").style.width = Math.max(0, Math.min(100 - (sl / 24) * 100, (st / 24) * 100)) + "%";
    $("seg-move").style.width = Math.max(0, Math.min(100 - ((sl + st) / 24) * 100, (mv / 24) * 100)) + "%";
    box.classList.toggle("over", used > 24);
    $("budget-text").textContent = used === 0 ? "Your 24 hours: enter sleep, study and activity to see how the day fits together."
      : used > 24 ? `Your 24 hours: these add up to ${+used.toFixed(1)} h. A day only has 24, so please check the numbers.`
        : `Your 24 hours: ${+sl.toFixed(1)} h sleep, ${+st.toFixed(1)} h study, ${+mv.toFixed(1)} h movement, leaving about ${+(24 - used).toFixed(1)} h for everything else.`;
  }

  document.querySelectorAll("#stress_level_group button").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll("#stress_level_group button").forEach((b) => b.setAttribute("aria-checked", String(b === btn)));
    $("stress_level").value = btn.dataset.value;
    clearError($("stress_level")); updateProgress();
  }));
  form.querySelectorAll("input:not([type=hidden]),select").forEach((el) => {
    const on = () => { clearError(el); setFormError(""); updateProgress(); updateLive(); };
    el.addEventListener("input", on); el.addEventListener("change", on);
  });

  /* ---------- states ---------- */
  const STATES = ["idle", "loading", "result", "error"];
  function showState(name) { STATES.forEach((s) => { $("state-" + s).hidden = s !== name; }); }
  function showError(label, copy) { $("error-label").textContent = label; $("error-copy").textContent = copy; showState("error"); }

  const levelClass = (l) => { l = String(l || "").toLowerCase(); return l.includes("risk") ? "risk" : l.includes("healthy") ? "healthy" : "mid"; };
  const CIRC = 2 * Math.PI * 72;
  $("ring-progress").style.strokeDasharray = CIRC;

  function countUp(el, to) {
    if (reduceMotion) { el.textContent = to.toFixed(1); return; }
    const t0 = performance.now(), dur = 1100;
    (function tick(now) { const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.textContent = (to * e).toFixed(1); if (k < 1) requestAnimationFrame(tick); })(t0);
  }

  function renderResultCard(data) {
    const g = data.guidance, score = data.predicted_mental_health_score;
    $("score-band").textContent = data.level;
    $("score-band").className = "level-pill " + levelClass(data.level);
    $("result-headline").textContent = g.headline;
    $("result-summary").textContent = g.summary;
    $("pressure-value").textContent = `${Math.round(g.pressure_index)} · ${g.pressure_label}`;
    $("driver-value").textContent = g.primary_root_cause_label || "None flagged";
    $("projected-wrap").hidden = !g.projected_score;
    if (g.projected_score) $("projected-value").textContent = `${score.toFixed(1)} → about ${g.projected_score.toFixed(1)}`;
    const chip = $("save-chip");
    chip.classList.toggle("off", !data.saved);
    chip.textContent = data.saved ? "Saved to your private history" : (data.save_error || "This result could not be saved right now.");
    const ring = $("ring-progress");
    ring.style.strokeDashoffset = CIRC;
    requestAnimationFrame(() => requestAnimationFrame(() => { ring.style.strokeDashoffset = CIRC * (1 - Math.max(0, Math.min(10, score)) / 10); }));
    countUp($("score-number"), score);
    window.MPFX && window.MPFX.setMood(g.mode, score.toFixed(1));
  }


  /* ---------- doctor-style prescription (from guidance.prescription; absent on older saved records) ---------- */
  const STATUS_CLS = { "On target": "ok", Mild: "mild", Moderate: "moderate", High: "high" };
  function renderPrescription(rx) {
    const sub = (t) => h("h4", { class: "rx-sub", text: t });
    const head = h("header", { class: "rx-head" },
      h("div", { class: "rx-mark", "aria-hidden": "true", text: "℞" }),
      h("div", { class: "rx-title" }, h("h3", { text: rx.title || "Your wellness prescription" }),
        h("p", { class: "rx-patient", text: rx.patient || "" })),
      h("div", { class: "rx-meta" }, h("span", { text: "Plan length" }), h("b", { text: rx.duration || "4 weeks" }),
        h("button", { class: "btn ghost small rx-print", type: "button", text: "Print", onclick: () => window.print() })));
    const impression = h("div", { class: "rx-impression" }, h("strong", { text: "Assessment" }), h("p", { text: rx.impression || "" }));

    const vitals = h("div", { class: "rx-vitals" }, (rx.vitals || []).map((v) =>
      h("div", { class: "rx-vital" }, h("span", { class: "rx-vl", text: v.label }), h("b", { text: v.value }), h("em", { text: "Target: " + v.target }),
        h("i", { class: "rx-chip " + (STATUS_CLS[v.status] || "ok"), text: v.status }))));

    const doses = h("div", { class: "rx-doses" }, (rx.doses || []).map((d, i) =>
      h("div", { class: "rx-dose" }, h("div", { class: "rx-n", text: String(i + 1) }),
        h("div", null, h("h5", { text: d.area }), h("p", { class: "rx-do", text: d.dose }), h("p", { class: "rx-when", text: d.when }), h("p", { class: "rx-why", text: d.why }), d.effect ? h("p", { class: "rx-effect", text: d.effect }) : null))));

    const routine = h("div", { class: "rx-routine" }, (rx.routine || []).map((r) =>
      h("div", { class: "rx-slot" }, h("h5", { text: r.slot }), h("ul", null, r.items.map((t) => h("li", { text: t }))))));

    const week = h("ol", { class: "rx-week" }, (rx.week_plan || []).map((d) => h("li", null, h("b", { text: d.day }), h("span", { text: d.task }))));
    const prog = h("div", { class: "rx-prog" }, (rx.progression || []).map((w) => h("div", { class: "rx-step" }, h("b", { text: w.week }), h("strong", { text: w.goal }), h("p", { text: w.focus }))));
    const lists = h("div", { class: "two-col rx-lists" },
      h("div", null, sub("Do"), h("ul", { class: "check-list" }, (rx.do || []).map((t) => h("li", { text: t })))),
      h("div", null, sub("Avoid"), h("ul", { class: "check-list watch" }, (rx.avoid || []).map((t) => h("li", { text: t })))));
    const track = h("div", { class: "rx-track" }, sub("Track every day"), h("ul", { class: "chip-list inline" }, (rx.track || []).map((t) => h("li", { text: t }))), h("p", { class: "rx-follow" }, h("b", { text: "Follow-up: " }), document.createTextNode(rx.followup || "")));
    const help = h("div", { class: "rx-help" }, h("h4", { text: "When to seek help" }), h("p", { text: rx.support || "" }), h("ul", null, (rx.warning_signs || []).map((t) => h("li", { text: t }))));

    return h("section", { class: "rp-section rx" }, head, impression,
      sub("Your numbers at a glance"), vitals,
      sub("Daily dosage"), doses,
      sub("Daily routine"), routine,
      sub("First 7 days"), week,
      sub("4-week progression"), prog,
      lists, track, help, h("p", { class: "disclaimer", text: rx.note || "" }));
  }

  /* ---------- report (used for the live result AND for saved records) ---------- */
  const sevClass = (l) => ({ Mild: "mild", Moderate: "moderate", High: "high" }[l] || "mild");
  const section = (title, sub, ...kids) => h("section", { class: "rp-section" }, h("h3", { text: title }), sub ? h("p", { class: "sub", text: sub }) : null, ...kids);
  const detail = (title, ...body) => h("details", null, h("summary", { text: title }), h("div", { class: "body" }, ...body));

  function renderReport(container, d) {
    container.replaceChildren();
    const g = d.guidance;
    if (!g) {
      container.append(h("p", { class: "empty", text: "This check-in was saved before personal root-cause analysis existed, so only the score is available." }));
      return;
    }
    const score = d.score, fill = [];   // fill = bar animations run after insertion

    container.append(h("div", { class: "rp-head" },
      h("div", null, h("h2", { text: g.headline }), h("p", { class: "lead", text: g.summary })),
      h("div", { class: "rp-score" }, h("strong", { text: score.toFixed(1) }), h("span", { text: `out of 10 · ${d.level}` }))));

    const pos = Math.max(0, Math.min(100, g.pressure_index));
    const marker = h("i", { style: "left:0%" });
    fill.push(() => { marker.style.left = `calc(${pos}% - 2px)`; });
    container.append(h("div", { class: "pressure" },
      h("div", { class: "pressure-top" }, h("span", { text: "Habit pressure from your own numbers" }), h("strong", { text: `${Math.round(g.pressure_index)} of 100 · ${g.pressure_label}` })),
      h("div", { class: "pressure-bar" }, marker)));

    if (d.notes && d.notes.length) container.append(h("div", { class: "insights" }, d.notes.map((n) => h("div", { class: "insight" }, h("h4", { text: "About your inputs" }), h("p", { text: n })))));

    const causes = g.root_causes || [];
    const why = section("Why your score looks like this",
      causes.length ? "Ranked by weight × how far each habit is from a healthy target. This is a pattern in your inputs, not a proven cause." : null);
    if (causes.length) {
      why.append(h("div", { class: "causes" }, causes.map((c) => {
        const bar = h("i", { style: "width:0%" });
        fill.push(() => { bar.style.width = Math.max(4, c.contribution_pct) + "%"; });
        return h("div", { class: "cause" }, h("div", { class: "rank", text: String(c.rank) }),
          h("div", null,
            h("div", { class: "cause-top" }, h("h4", { text: c.label }), h("span", { class: "sev " + sevClass(c.severity_label), text: `${c.severity_label} · ${c.contribution_pct}% of your habit pressure` })),
            h("div", { class: "bar" }, bar),
            h("div", { class: "vt" }, h("span", null, "You: ", h("b", { text: c.your_value })), h("span", null, "Target: ", h("b", { text: c.target }))),
            h("p", { class: "why", text: c.why }),
            c.model_gain ? h("p", { class: "model-check", text: `Model check: if only this reached its target, the predicted score would rise by about ${c.model_gain.toFixed(2)}.` }) : null));
      })));
    } else {
      why.append(h("p", { class: "sub", text: g.mode === "maintain" ? "None of your habits is far from its target, so there is nothing to fix. That is good news." : "None of your tracked habits stands out. Your score may reflect things this tool cannot see, so the steps below are general." }));
    }
    if (g.stress_signal && g.stress_signal.severity >= 0.3) why.append(h("p", { class: "stress-signal", text: `You reported ${g.stress_signal.level.toLowerCase()} stress. That is how you feel, so it is treated as a signal rather than a habit to fix directly.` }));
    if ((g.combined_insights || []).length) why.append(h("div", { class: "insights" }, g.combined_insights.map((i) => h("div", { class: "insight" }, h("h4", { text: i.title }), h("p", { text: i.text })))));
    container.append(why);

    if ((g.recommendations || []).length) {
      const plans = g.recommendations.map((r) => {
        const total = r.steps.length, prog = h("p", { class: "plan-progress", text: `0 of ${total} steps done` });
        const list = h("ul", { class: "steps" }, r.steps.map((s) => h("li", null, h("label", null, h("input", { type: "checkbox" }), h("span", { text: s })))));
        list.addEventListener("change", () => { prog.textContent = `${list.querySelectorAll("input:checked").length} of ${total} steps done`; });
        return h("article", { class: "plan" },
          h("div", { class: "plan-top" }, h("span", null, "Priority ", h("b", { text: String(r.priority) })), h("span", { text: r.title })),
          h("h4", { text: r.focus }),
          h("div", { class: "first-step" }, h("strong", { text: "Start today" }), r.first_step),
          list, prog);
      });
      container.append(section("Your action plan", "Built from your own numbers. Start with priority 1 and change one thing at a time.", h("div", { class: "plans" }, plans)));
    }

    if (g.prescription) container.append(renderPrescription(g.prescription));

    if ((g.strengths || []).length) {
      const strengthCol = h("div", null, h("h4", { text: "What is already working" }), h("ul", { class: "chip-list", style: "margin-top:10px" }, g.strengths.map((s) => h("li", null, h("b", { text: s.label }), s.detail))));
      const keepCol = (g.maintenance || []).length ? h("div", null, h("h4", { text: "How to keep it that way" }), h("ul", { class: "check-list", style: "margin-top:10px" }, g.maintenance.map((m) => h("li", { text: m })))) : null;
      container.append(section(g.mode === "maintain" ? "You are doing well" : "Build on your strengths", null, h("div", { class: "two-col" }, strengthCol, keepCol)));
    }
    if ((g.watch || []).length) container.append(section("Keep an eye on", null, h("ul", { class: "check-list watch", style: "margin-top:12px" }, g.watch.map((w) => h("li", { text: w })))));
    if (g.support_note) container.append(h("div", { class: "callout", text: g.support_note }));

    const more = h("div", { class: "more" });
    const comps = Object.entries(d.components || {});
    if (comps.length) more.append(detail("How the models scored this", h("p", { text: "The final score is the average of these models. When they agree closely, the estimate is steadier." }), comps.map(([k, v]) => h("div", { class: "kv" }, h("span", { text: k }), h("b", { text: Number(v).toFixed(2) })))));
    if ((d.explanations || []).length) more.append(detail("What moved the score most (model what-if)", h("p", { text: "How the score changes when one input is replaced by a typical value. This describes the model, not you, and is not causal." }),
      d.explanations.slice(0, 6).map((x) => h("div", { class: "kv" }, h("span", { text: String(x.feature).replaceAll("_", " ") }), h("b", { class: x.impact > 0.03 ? "up" : x.impact < -0.03 ? "down" : "", text: (x.impact > 0 ? "+" : "") + Number(x.impact).toFixed(2) })))));
    if ((g.weights || []).length) more.append(detail("How root causes are ranked", h("p", { text: "Each habit gets a severity from 0 to 1 against a healthy target. Severity × weight gives its impact. Stress is treated as the signal, so it is not ranked as a habit." }),
      g.weights.map((w) => h("div", { class: "kv" }, h("span", { text: w.label + (w.kind === "signal" ? " (signal)" : "") }), h("b", { text: "weight " + w.weight })))));
    if (more.children.length) container.append(more);

    container.append(h("p", { class: "disclaimer", text: g.disclaimer }));
    requestAnimationFrame(() => requestAnimationFrame(() => fill.forEach((f) => f())));
  }

  /* ---------- submit ---------- */
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); clearAllErrors();
    try { if (!localStorage.getItem("mindpulse_access_token")) { window.dispatchEvent(new Event("show-auth")); return; } } catch (_) { window.dispatchEvent(new Event("show-auth")); return; }
    const payload = collect(), { errs, formMsg } = validate(payload);
    if (errs.length || formMsg) {
      errs.forEach(([el, msg]) => setError(el, msg));
      if (formMsg) setFormError(formMsg);
      const first = errs[0] && errs[0][0];
      if (first && first.type !== "hidden") first.focus();
      else if (first) $("stress_level_group").querySelector("button").focus();
      return;
    }
    submitBtn.disabled = true; submitBtn.classList.add("loading"); showState("loading");
    // Clear the check-in immediately after submit, while retaining the captured payload.
    form.reset(); clearAllErrors();
    document.querySelectorAll("#stress_level_group button").forEach((b) => b.setAttribute("aria-checked", "false"));
    $("stress_level").value = ""; updateProgress(); updateLive();
    try {
      const { ok, status, body } = await api("/predict", { method: "POST", body: JSON.stringify(payload) });
      if (status === 422) {
        let general = "";
        (Array.isArray(body && body.detail) ? body.detail : []).forEach((err) => {
          const key = Array.isArray(err.loc) ? err.loc[err.loc.length - 1] : null;
          const msg = String(err.msg || "Invalid value.").replace(/^Value error, /, "");
          if (!(typeof key === "string" && $(key) && setError($(key), msg))) general = general || msg;
        });
        if (general) setFormError(general);
        showState("idle");
        return;
      }
      if (!ok) { showError(status === 503 ? "Not saved" : "Prediction failed", (body && body.detail) || `The server answered with status ${status}.`); return; }
      if (!body || typeof body.predicted_mental_health_score !== "number" || !body.guidance) { showError("Unexpected response", "The server returned data this page does not understand. Restart the API and try again."); return; }
      const score = Math.max(0, Math.min(10, body.predicted_mental_health_score));
      showState("result"); renderResultCard(body);
      renderReport($("report-body"), { score, level: body.level, guidance: body.guidance, notes: body.input_notes, components: body.component_predictions, explanations: body.explanations });
      $("report").hidden = false; $("nav-report").hidden = false;
      setTimeout(() => { $("report").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" }); $("report-body").focus({ preventScroll: true }); }, 650);
      window.dispatchEvent(new CustomEvent("prediction-done"));
    } catch (_) {
      showError("Cannot reach the server", "Start the backend from the project folder with: uvicorn api.main:app --reload");
    } finally { submitBtn.disabled = false; submitBtn.classList.remove("loading"); }
  });

  function reset() {
    form.reset(); clearAllErrors();
    document.querySelectorAll("#stress_level_group button").forEach((b) => b.setAttribute("aria-checked", "false"));
    $("stress_level").value = "";
    $("report").hidden = true; $("nav-report").hidden = true; $("report-body").replaceChildren();
    showState("idle"); updateProgress(); updateLive();
    window.MPFX && window.MPFX.setMood("idle");
    $("assessment").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth" });
  }
  $("reset-btn").addEventListener("click", reset);
  $("error-retry-btn").addEventListener("click", () => showState("idle"));

  /* ---------- status + options ---------- */
  async function refreshStatus() {
    try {
      const { ok, body } = await api("/health");
      if (!ok) throw new Error("health");
      $("api-dot").className = "dot ok"; $("api-status").textContent = "Service online";
      const db = body.database || {};
      $("db-dot").className = "dot " + (db.online ? "ok" : "bad");
      $("db-status").textContent = db.online ? "Reports saving on" : "Reports not saving";
    } catch (_) {
      $("api-dot").className = "dot bad"; $("api-status").textContent = "Service offline";
      $("db-dot").className = "dot"; $("db-status").textContent = "Status unknown";
    }
  }

  async function loadStaticInfo() {
    try {
      // Model metrics are intentionally not rendered in the public UI.
      await api("/model-info");
    } catch (_) { /* the status pill already shows the API state */ }
    let academicDataset = null;
    let genders = FALLBACK.genders, levels = FALLBACK.academic_levels, employment = FALLBACK.employment_statuses, platforms = FALLBACK.platforms, purposes = FALLBACK.purposes, countries = FALLBACK.countries;
    try {
      const { ok, body } = await api("/options");
      if (ok) {
        genders = body.genders || genders; levels = body.academic_levels || levels; employment = body.employment_statuses || employment; platforms = body.platforms || platforms;
        purposes = body.purposes || purposes; countries = body.countries || countries; RANGES = body.trained_ranges || RANGES;
        academicDataset = body.academic_dataset && body.academic_dataset.stages && body.academic_dataset.stages.length ? body.academic_dataset : null;
      }
    } catch (_) { /* fallback lists above are used */ }
    if (!Array.isArray(countries) || !countries.length) countries = FALLBACK.countries;
    if (!Array.isArray(employment) || !employment.length) employment = FALLBACK.employment_statuses;
    const fillSelect = (id, values) => {
      const sel = $(id), keep = sel.value;
      sel.querySelectorAll("option:not([disabled])").forEach((o) => o.remove());
      values.forEach((v) => sel.append(h("option", { text: v, value: v })));
      if (keep && values.includes(keep)) sel.value = keep;
    };
    /* Academic level: the dataset's own labels (Dataset sheet) grouped by its Education_Stage_Standard, narrowed to the chosen country.
       If the API is offline, the nine model categories are shown instead. */
    const FALLBACK_GROUPS = [
      ["School", ["Early Childhood / Pre-primary", "Primary School", "Middle School / Lower Secondary", "High School / Upper Secondary"]],
      ["College, university and beyond", ["Diploma / Vocational", "Undergraduate", "Postgraduate (Master's)", "Doctoral (PhD)"]],
      ["Not listed", ["Other"]],
    ];
    const STAGE_TITLE = { "Pre-primary": "Pre-primary", "Primary": "Primary", "Lower Secondary": "Lower secondary", "Upper Secondary": "Upper secondary",
      "Vocational / Short-cycle": "Vocational / diploma", "Bachelor / Undergraduate": "Bachelor / undergraduate", "Master / Postgraduate": "Master / postgraduate", "Doctoral": "Doctoral", "Other": "Other" };
    /* AGE RULE (built from the dataset: which Education_Stage_Standard values actually occur at each age).
       Under 18 never shows Undergraduate/Master/PhD; Master starts at 21, PhD at 24; ages 5-6 show only Pre-primary + Primary. */
    const AGE_STAGES = {
      5: ["Pre-primary", "Primary"], 6: ["Pre-primary", "Primary"],
      7: ["Primary"], 8: ["Primary"], 9: ["Primary"], 10: ["Primary"],
      11: ["Primary", "Lower Secondary"], 12: ["Primary", "Lower Secondary"], 13: ["Lower Secondary"],
      14: ["Lower Secondary", "Upper Secondary"], 15: ["Lower Secondary", "Upper Secondary"], 16: ["Lower Secondary", "Upper Secondary"],
      17: ["Upper Secondary", "Vocational / Short-cycle", "Bachelor / Undergraduate", "Other"],
      18: ["Upper Secondary", "Vocational / Short-cycle", "Bachelor / Undergraduate", "Other"],
      19: ["Vocational / Short-cycle", "Bachelor / Undergraduate", "Other"], 20: ["Vocational / Short-cycle", "Bachelor / Undergraduate", "Other"],
      21: ["Vocational / Short-cycle", "Bachelor / Undergraduate", "Master / Postgraduate", "Other"],
      22: ["Vocational / Short-cycle", "Bachelor / Undergraduate", "Master / Postgraduate", "Other"],
      23: ["Vocational / Short-cycle", "Bachelor / Undergraduate", "Master / Postgraduate", "Other"],
      24: ["Vocational / Short-cycle", "Bachelor / Undergraduate", "Master / Postgraduate", "Doctoral", "Other"],
    };
    const stagesForAge = (age) => {
      if (!Number.isInteger(age) || age < 1) return null;           /* no valid age yet: show everything */
      if (age < 5) return ["Pre-primary"];
      return AGE_STAGES[Math.min(age, 24)];                         /* 24 and above share one rule */
    };
    const LEVEL_STAGE = { "Early Childhood / Pre-primary": "Pre-primary", "Primary School": "Primary", "Middle School / Lower Secondary": "Lower Secondary",
      "High School / Upper Secondary": "Upper Secondary", "Diploma / Vocational": "Vocational / Short-cycle", "Undergraduate": "Bachelor / Undergraduate",
      "Postgraduate (Master's)": "Master / Postgraduate", "Doctoral (PhD)": "Doctoral", "Other": "Other" };
    const readAge = () => { const v = $("age").value.trim(); return /^\d{1,3}$/.test(v) ? parseInt(v, 10) : null; };

    const fillAcademic = (country) => {
      const sel = $("academic_level"), keep = sel.value;
      sel.querySelectorAll("option:not([disabled]), optgroup").forEach((o) => o.remove());
      const age = readAge(), okStages = stagesForAge(age), okStage = (st) => !okStages || okStages.includes(st);
      let groups, shown = 0, relaxed = false;
      if (academicDataset) {
        const byCountry = country && academicDataset.by_country && academicDataset.by_country[country] ? new Set(academicDataset.by_country[country]) : null;
        const build = (useCountry) => academicDataset.stages.filter((st) => okStage(st.stage))
          .map((st) => [STAGE_TITLE[st.stage] || st.stage, st.labels.filter((l) => !useCountry || !byCountry || byCountry.has(l))]);
        groups = build(true);
        if (!groups.some(([, items]) => items.length)) { groups = build(false); relaxed = !!byCountry; }   /* country has no label for this age: keep the age rule, drop the country filter */
      } else {
        groups = FALLBACK_GROUPS.map(([t, items]) => [t, items.filter((v) => levels.includes(v) && okStage(LEVEL_STAGE[v]))]);
      }
      const values = [];
      groups.forEach(([title, items]) => {
        if (!items.length) return;
        const g = h("optgroup", { label: title });
        items.forEach((v) => { values.push(v); shown++; g.append(h("option", { value: v, text: v })); });
        sel.append(g);
      });
      sel.value = keep && values.includes(keep) ? keep : "";
      const hint = $("academic-hint");
      if (hint) {
        if (age == null) hint.textContent = country ? "Enter the age to narrow the education levels." : "Enter the age and pick a country to narrow the education levels.";
        else hint.textContent = `${shown} education level${shown === 1 ? "" : "s"} for age ${age}${country && academicDataset && !relaxed ? ` in ${country}` : ""}.`;
      }
      if (sel.__ddSync) sel.__ddSync();
    };
    fillSelect("gender", genders);
    fillAcademic($("country").value);
    fillSelect("employment_status", employment);
    fillSelect("country", countries);
    fillSelect("most_used_platform", platforms);
    fillSelect("purpose_of_use", purposes);
    $("country").addEventListener("change", () => { fillAcademic($("country").value); updateLive(); });
    $("age").addEventListener("input", () => { fillAcademic($("country").value); });
    $("age").addEventListener("change", () => { fillAcademic($("country").value); });
    form.addEventListener("reset", () => setTimeout(() => fillAcademic($("country").value), 0));
    updateLive();
  }

  window.MP = { h, api, API_BASE, CID, renderReport, refreshStatus, levelClass };

  // Subtle 3D glass interaction. It is disabled for reduced-motion users.
  if (!reduceMotion) {
    /* Cards that contain form controls (.form-card, .auth-card) are NOT tilted: a 3D-transformed ancestor stops native <select> lists from opening/painting in Chrome and Edge. */
    document.querySelectorAll(".card:not(.form-card), .strip, .profile-card, .profile-stat").forEach((card) => {
      card.addEventListener("pointermove", (e) => {
        const r = card.getBoundingClientRect();
        const rx = ((e.clientY - r.top) / r.height - .5) * -3.5;
        const ry = ((e.clientX - r.left) / r.width - .5) * 3.5;
        card.style.transform = `perspective(1100px) rotateX(${rx}deg) rotateY(${ry}deg) translateZ(2px)`;
      });
      card.addEventListener("pointerleave", () => { card.style.transform = ""; });
    });
  }
  window.addEventListener("prediction-done", refreshStatus);
  updateProgress(); updateLive(); loadStaticInfo(); refreshStatus();
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 30000);
})();