/* MindPulse custom dropdown.
   Replaces the browser's native <select> popup (which was not opening / was clipped inside the glass 3D cards)
   with an in-page list. The real <select> stays in the DOM (hidden), so form values, validation and
   existing code keep working. */
(() => {
  "use strict";
  let openDd = null;

  function closeOpen() { if (openDd) openDd.close(); }
  document.addEventListener("pointerdown", (e) => { if (openDd && !openDd.root.contains(e.target) && !openDd.menu.contains(e.target)) closeOpen(); });
  window.addEventListener("resize", closeOpen);
  window.addEventListener("scroll", (e) => { if (openDd && Date.now() - openDd.at > 250 && !openDd.menu.contains(e.target)) closeOpen(); }, true);

  function enhance(sel) {
    if (!sel || sel.dataset.dd) return;
    sel.dataset.dd = "1";
    const root = document.createElement("div"); root.className = "dd";
    const btn = document.createElement("button"); btn.type = "button"; btn.className = "dd-btn";
    btn.setAttribute("aria-haspopup", "listbox"); btn.setAttribute("aria-expanded", "false");
    const label = document.createElement("span"); label.className = "dd-label"; btn.append(label);
    const menu = document.createElement("div"); menu.className = "dd-menu"; menu.setAttribute("role", "listbox"); menu.hidden = true;
    sel.parentNode.insertBefore(root, sel); root.append(btn, sel); sel.classList.add("dd-native"); sel.tabIndex = -1; sel.setAttribute("aria-hidden", "true");
    const lbl = document.querySelector(`label[for="${sel.id}"]`);
    if (lbl) lbl.addEventListener("click", (e) => { e.preventDefault(); btn.focus(); });
    sel.focus = () => btn.focus();

    let items = [], active = -1;
    const sync = () => {
      const o = sel.options[sel.selectedIndex];
      const empty = !o || !sel.value;
      label.textContent = o ? o.textContent : "Select";
      btn.classList.toggle("dd-placeholder", empty);
    };

    function build() {
      menu.textContent = ""; items = [];
      const add = (o, parent) => {
        if (o.disabled && !o.value) return;                       // skip the "Select…" placeholder
        const it = document.createElement("div"); it.className = "dd-item"; it.setAttribute("role", "option");
        it.textContent = o.textContent; it.dataset.value = o.value;
        if (o.value === sel.value) { it.classList.add("dd-selected"); it.setAttribute("aria-selected", "true"); }
        it.addEventListener("pointerdown", (e) => e.preventDefault());
        it.addEventListener("click", () => choose(o.value));
        it.addEventListener("pointermove", () => setActive(items.indexOf(it), false));
        parent.append(it); items.push(it);
      };
      [...sel.children].forEach((c) => {
        if (c.tagName === "OPTGROUP") {
          const g = document.createElement("div"); g.className = "dd-group"; g.textContent = c.label; menu.append(g);
          [...c.children].forEach((o) => add(o, menu));
        } else add(c, menu);
      });
      if (!items.length) { const e = document.createElement("div"); e.className = "dd-empty"; e.textContent = "No options available"; menu.append(e); }
    }
    function setActive(i, scroll = true) {
      items.forEach((x) => x.classList.remove("dd-active"));
      active = i;
      if (items[i]) { items[i].classList.add("dd-active"); if (scroll) { const it = items[i], top = it.offsetTop, bot = top + it.offsetHeight; if (top < menu.scrollTop) menu.scrollTop = top - 30; else if (bot > menu.scrollTop + menu.clientHeight) menu.scrollTop = bot - menu.clientHeight + 6; } }
    }
    function place() {
      const r = btn.getBoundingClientRect(), vh = window.innerHeight;
      const below = vh - r.bottom - 12, above = r.top - 12;
      const up = below < 200 && above > below;
      menu.style.left = r.left + "px"; menu.style.width = r.width + "px";
      menu.style.maxHeight = Math.max(140, Math.min(320, up ? above : below)) + "px";
      if (up) { menu.style.top = "auto"; menu.style.bottom = (vh - r.top + 6) + "px"; } else { menu.style.bottom = "auto"; menu.style.top = (r.bottom + 6) + "px"; }
    }
    function open() {
      if (openDd && openDd.root !== root) closeOpen();
      build(); document.body.append(menu); menu.hidden = false; place();
      btn.setAttribute("aria-expanded", "true"); root.classList.add("dd-open");
      const si = items.findIndex((x) => x.classList.contains("dd-selected"));
      setActive(si >= 0 ? si : 0);
      openDd = { root, menu, close, at: Date.now() };
    }
    function close() {
      menu.hidden = true; menu.remove(); btn.setAttribute("aria-expanded", "false"); root.classList.remove("dd-open");
      if (openDd && openDd.root === root) openDd = null;
    }
    function choose(v) {
      sel.value = v; sync(); close(); btn.focus();
      sel.dispatchEvent(new Event("input", { bubbles: true })); sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
    btn.addEventListener("click", () => (menu.hidden ? open() : close()));
    btn.addEventListener("keydown", (e) => {
      const isOpen = !menu.hidden;
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key) && !isOpen) { e.preventDefault(); open(); return; }
      if (!isOpen) { if (e.key.length === 1) typeahead(e.key); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(items.length - 1, active + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(0, active - 1)); }
      else if (e.key === "Home") { e.preventDefault(); setActive(0); }
      else if (e.key === "End") { e.preventDefault(); setActive(items.length - 1); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (items[active]) choose(items[active].dataset.value); }
      else if (e.key === "Escape" || e.key === "Tab") close();
      else if (e.key.length === 1) typeahead(e.key);
    });
    let buf = "", t;
    function typeahead(ch) {
      buf += ch.toLowerCase(); clearTimeout(t); t = setTimeout(() => (buf = ""), 600);
      if (menu.hidden) build();
      const i = items.findIndex((x) => x.textContent.toLowerCase().startsWith(buf));
      if (i >= 0) { if (menu.hidden) { sel.value = items[i].dataset.value; sync(); sel.dispatchEvent(new Event("change", { bubbles: true })); } else setActive(i); }
    }
    new MutationObserver(sync).observe(sel, { childList: true, subtree: true, attributes: true });
    sel.addEventListener("change", sync);
    if (sel.form) sel.form.addEventListener("reset", () => setTimeout(sync, 0));
    sel.__ddSync = sync; sync();
  }

  function enhanceAll() { document.querySelectorAll("select").forEach(enhance); }
  window.MPDropdown = { enhance, enhanceAll };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", enhanceAll); else enhanceAll();
})();
