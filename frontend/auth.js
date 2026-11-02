/* MindPulse account UI. Authentication state is stored only as a short-lived
   signed token; the server remains the authority for user identity/data scope. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const API_BASE = window.MP ? window.MP.API_BASE : (location.origin + "");
  const TOKEN_KEY = "mindpulse_access_token";
  let stage = "signin", verifyEmail = "", resetEmail = "", resetToken = null;

  const toast = (o) => { try { window.MPToast && window.MPToast.show(o); } catch (_) {} };
  const firstName = (u) => String((u && u.name) || "").trim().split(/\s+/)[0] || "there";
  function token() { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; } }
  function saveToken(v) { try { localStorage.setItem(TOKEN_KEY, v); } catch (_) {} }
  function clearToken() { try { localStorage.removeItem(TOKEN_KEY); } catch (_) {} }
  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    const t = token(); if (t) headers.Authorization = `Bearer ${t}`;
    const r = await fetch(API_BASE + path, { ...opts, headers });
    let body = null; try { body = await r.json(); } catch (_) {}
    return { ok: r.ok, status: r.status, body };
  }
  function setError(id, msg) { const e = $(id); if (Array.isArray(msg)) msg = msg.map(x => (x && x.msg ? ((x.loc && x.loc.length ? x.loc[x.loc.length - 1] + ": " : "") + String(x.msg).replace(/^Value error, /, "")) : String(x))).join(" "); else if (msg && typeof msg !== "string") msg = "Something went wrong. Please try again."; if (e) { e.textContent = msg || ""; e.classList.toggle("show", !!msg); } }
  function busy(form, yes) { if (!form) return; const b = form.querySelector(".auth-submit"); if (!b) return; b.disabled = yes; b.classList.toggle("loading", yes); }
  function showView(name) {
    stage = name;
    ["signin", "signup", "verify", "forgot", "reset"].forEach(v => { $("auth-" + v).hidden = v !== name; });
    const titles = {signin:["Welcome back","Sign in to keep your wellness check-ins and reports connected to your account."],signup:["Create your account","A private wellness space for your check-ins, reports and history."],verify:["Verify your email","One small step before your private wellness space is ready."],forgot:["Recover your account","We will guide you through a secure password reset."],reset:["Choose a new password","Finish the reset securely, then sign in again."]};
    $("auth-title").textContent = titles[name][0]; $("auth-subtitle").textContent = titles[name][1];
    const f = $("auth-" + name); if (f) { f.classList.remove("view-in"); void f.offsetWidth; f.classList.add("view-in"); }
  }
  function showApp(user) {
    $("auth-screen").classList.add("hidden-auth"); document.body.classList.remove("auth-mode");
    document.querySelector("main").classList.remove("app-locked");
    $("nav-user-name").textContent = user ? user.name : "";
    if (user) { $("profile-name").textContent = user.name; $("profile-email").textContent = user.email; $("profile-avatar").textContent = (user.name || "M").trim().charAt(0).toUpperCase(); }
    window.dispatchEvent(new Event("auth-ready"));
    window.scrollTo({ top: 0, behavior: "smooth" });
    loadProfileStats();
  }
  function showAuth() {
    $("auth-screen").classList.remove("hidden-auth"); document.body.classList.add("auth-mode"); document.querySelector("main").classList.add("app-locked");
    window.dispatchEvent(new Event("auth-logged-out"));
    $("nav-user-name").textContent = ""; $("profile-name").textContent = "—"; $("profile-email").textContent = "—"; $("profile-avatar").textContent = "?";
    ["profile-checkins", "profile-latest-score", "profile-average"].forEach((id) => { if ($(id)) $(id).textContent = "—"; });
    showView(stage);
  }
  function parseTokenPayload(t) { try { return JSON.parse(atob(t.split(".")[0].replace(/-/g,"+").replace(/_/g,"/") + "=".repeat((4-t.split(".")[0].length%4)%4))); } catch (_) { return null; } }
  async function loadProfileStats() {
    if (!token()) return;
    const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
    const r = await api("/history?limit=100").catch(() => null);
    if (!r || !r.ok || !r.body) { return; }                    // keep what is shown; do not overwrite with zeros on a temporary error
    const recs = r.body.records || [], n = r.body.count ?? recs.length;
    const scores = recs.map((x) => Number(x.predicted_score)).filter(Number.isFinite);
    set("profile-checkins", String(n));
    set("profile-latest-score", scores.length ? scores[0].toFixed(1) + " / 10" : "—");
    set("profile-average", scores.length ? (scores.reduce((a, c) => a + c, 0) / scores.length).toFixed(1) + " / 10" : "—");
    const note = $("profile-latest-note");
    if (note) note.textContent = scores.length > 1 ? (scores[0] - scores[1] >= 0.05 ? `Up ${(scores[0] - scores[1]).toFixed(1)} since the check-in before` : scores[1] - scores[0] >= 0.05 ? `Down ${(scores[1] - scores[0]).toFixed(1)} since the check-in before` : "Steady since the check-in before") : "From your most recent check-in";
    const an = $("profile-average-note"); if (an) an.textContent = n ? `Across ${Math.min(n, 100)} check-in${n === 1 ? "" : "s"}` : "Complete a check-in to see this";
  }
  window.addEventListener("prediction-done", loadProfileStats);   // keeps the profile in step after every check-in or delete
  function afterLogin(body, kind) {
    saveToken(body.access_token); showApp(body.user);
    const n = firstName(body.user);
    if (kind === "verified") toast({ type: "success", title: `Email verified. Welcome, ${n}!`, text: "Your private wellness space is ready. Start your first check-in whenever you like." });
    else toast({ type: "welcome", title: `Welcome back, ${n}!`, text: "Good to see you again. Ready for today's check-in?" });
  }

  document.querySelectorAll("[data-auth-view]").forEach(b => b.addEventListener("click", () => { showView(b.dataset.authView); }));
  document.querySelectorAll("[data-toggle-password]").forEach(b => b.addEventListener("click", () => { const i=$(b.dataset.togglePassword); i.type=i.type==="password"?"text":"password"; b.textContent=i.type==="password"?"Show":"Hide"; }));
  $("auth-signup-password").addEventListener("input", e => { const v=e.target.value; let n=0; if(v.length>=8)n++; if(/[A-Za-z]/.test(v))n++; if(/\d/.test(v))n++; if(/[^A-Za-z0-9]/.test(v))n++; $("password-strength-bar").style.width=[0,25,50,75,100][n]+"%"; $("password-strength-text").textContent=n>=4?"Strong password":n>=3?"Good password":n>=2?"Add more strength":"Use a letter and number"; });

  $("auth-signin").addEventListener("submit", async e => { e.preventDefault(); const form=e.currentTarget; setError("signin-error",""); busy(form,true); const body={email:$("auth-login-email").value.trim(),password:$("auth-login-password").value}; form.reset(); const r=await api("/auth/signin",{method:"POST",body:JSON.stringify(body)}).catch(()=>null); busy(form,false); if(!r){setError("signin-error","Server unavailable. Start the API and try again.");return;} if(!r.ok){setError("signin-error",r.body?.detail||"Sign in failed."); if(r.status===403){verifyEmail=body.email; $("verify-email-label").textContent=verifyEmail; showView("verify");} return;} afterLogin(r.body); });

  $("auth-signup").addEventListener("submit", async e => { e.preventDefault(); const form=e.currentTarget; setError("signup-error",""); const body={name:$("auth-signup-name").value.trim(),email:$("auth-signup-email").value.trim(),password:$("auth-signup-password").value}; if(body.name.length<2){setError("signup-error","Please enter your full name (at least 2 characters).");return;} if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email)){setError("signup-error","Please enter a valid email address.");return;} if(body.password.length<8){setError("signup-error","Password must be at least 8 characters.");return;} if(!/[A-Za-z]/.test(body.password)||!/\d/.test(body.password)){setError("signup-error","Password must contain at least one letter and one number.");return;} busy(form,true); const r=await api("/auth/signup",{method:"POST",body:JSON.stringify(body)}).catch(()=>null); busy(form,false); if(!r){setError("signup-error","Server unavailable.");return;} if(!r.ok){setError("signup-error",r.body?.detail||"Could not create the account.");return;} verifyEmail=body.email; $("verify-email-label").textContent=verifyEmail; showView("verify"); toast({ type: "info", title: "Account created. Check your email", text: `We sent a 6-digit OTP code to ${verifyEmail}. Enter it to activate your account.`, ms: 9000 }); });

  $("auth-verify").addEventListener("submit", async e => { e.preventDefault(); const form=e.currentTarget; setError("verify-error",""); busy(form,true); const body={email:verifyEmail,code:$("auth-verify-code").value.trim(),token:null}; const r=await api("/auth/verify-signup",{method:"POST",body:JSON.stringify(body)}).catch(()=>null); busy(form,false); if(!r || !r.ok){setError("verify-error",r?.body?.detail||"Verification failed.");return;} afterLogin(r.body, "verified"); });
  $("resend-verify").addEventListener("click", async () => { const r=await api("/auth/resend",{method:"POST",body:JSON.stringify({email:verifyEmail})}).catch(()=>null); setError("verify-error",""); if (r && r.ok) toast({ type: "info", title: "New code sent", text: `Check ${verifyEmail} for your new OTP code.` }); else setError("verify-error",r?.body?.detail||"Could not resend the code."); });

  $("auth-forgot").addEventListener("submit", async e => { e.preventDefault(); const form=e.currentTarget; setError("forgot-error",""); busy(form,true); resetEmail=$("auth-forgot-email").value.trim(); const r=await api("/auth/forgot",{method:"POST",body:JSON.stringify({email:resetEmail})}).catch(()=>null); busy(form,false); if(!r || !r.ok){setError("forgot-error",r?.body?.detail||"Could not send reset email.");return;} $("auth-reset-email").value=resetEmail; showView("reset"); setError("reset-error",""); toast({ type: "info", title: "Reset code sent. Check your email", text: `Enter the OTP code we sent to ${resetEmail} and choose a new password.`, ms: 9000 }); });

  $("auth-reset").addEventListener("submit", async e => { e.preventDefault(); const form=e.currentTarget; setError("reset-error",""); busy(form,true); const body={email:$("auth-reset-email").value.trim(),code:$("auth-reset-code").value.trim()||null,token:resetToken,new_password:$("auth-reset-password").value}; const r=await api("/auth/reset",{method:"POST",body:JSON.stringify(body)}).catch(()=>null); busy(form,false); if(!r || !r.ok){setError("reset-error",r?.body?.detail||"Could not change password.");return;} showView("signin"); setError("signin-error",""); toast({ type: "success", title: "Password changed", text: "Please sign in with your new password." }); });

  $("logout-btn").addEventListener("click", async () => {
    const t = token();
    if (t) { try { await api("/auth/logout", { method: "POST" }); } catch (_) {} }
    clearToken(); showAuth(); $("auth-login-password").value=""; showView("signin");
    toast({ type: "info", title: "Signed out", text: "See you soon. Your reports stay private in your account." });
  });
  window.addEventListener("show-auth", showAuth); window.addEventListener("auth-expired", () => { clearToken(); showAuth(); setError("signin-error","Your session expired. Please sign in again."); });

  (async () => {
    const qs=new URLSearchParams(location.search); const verify=qs.get("verify"), reset=qs.get("reset");
    if (verify) { const p=parseTokenPayload(verify); verifyEmail=p?.email||""; $("verify-email-label").textContent=verifyEmail||"your email"; showView("verify"); const r=await api("/auth/verify-signup",{method:"POST",body:JSON.stringify({email:verifyEmail,code:"000000",token:verify})}).catch(()=>null); if(r?.ok) { afterLogin(r.body, "verified"); history.replaceState({},"",location.pathname); } else if(r?.body?.detail) setError("verify-error",r.body.detail); }
    else if (reset) { const p=parseTokenPayload(reset); resetToken=reset; resetEmail=p?.email||""; $("auth-reset-email").value=resetEmail; showView("reset"); history.replaceState({},"",location.pathname); }
    else if (token()) {
      const r=await api("/auth/me").catch(()=>null);
      if (r?.ok) { showApp(r.body); toast({ type: "welcome", title: `Welcome, ${firstName(r.body)}!`, text: "You are here to check your mental wellness analysis. Start with today's check-in." }); }
      else if (!r) { showAuth(); setError("signin-error","Server unavailable. Start the API, then refresh this page. You are still signed in on this device."); }
      else { clearToken(); showAuth(); }
    }
    else showAuth();
  })();
})();