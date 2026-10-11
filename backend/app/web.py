"""The website (one self-contained page, served at "/").

It talks to POST /api/plan/stream and shows the agents working live, then the finished plan.
No build step, no external libraries, so it deploys together with the API.
"""

PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Travel Planner</title>
<style>
:root{
  --bg:#f6f7f4; --card:#ffffff; --ink:#1d2a26; --muted:#64706b; --line:#e3e7e2;
  --brand:#0f766e; --brand-ink:#ffffff; --soft:#e6f4f1; --warn:#b45309; --warn-bg:#fef3e2;
  --bad:#b91c1c; --good:#15803d; --live:#15803d; --est:#b45309;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#111816; --card:#1a2420; --ink:#e8efec; --muted:#93a39c; --line:#2a3732;
         --brand:#2dd4bf; --brand-ink:#04211d; --soft:#16312d; --warn:#fbbf24; --warn-bg:#2d2412;
         --bad:#f87171; --good:#4ade80; --live:#4ade80; --est:#fbbf24; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:0 16px 64px}
header{padding:28px 0 8px}
h1{margin:0;font-size:1.8rem;letter-spacing:-.02em}
.sub{color:var(--muted);margin:4px 0 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-top:16px}
h2{margin:0 0 12px;font-size:1.1rem}
form .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
label{display:block;font-size:.8rem;color:var(--muted);margin-bottom:4px}
input,select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font:inherit}
input:focus,select:focus{outline:2px solid var(--brand);outline-offset:1px}
button.go{margin-top:14px;width:100%;padding:13px;border:0;border-radius:12px;background:var(--brand);color:var(--brand-ink);font-weight:600;font-size:1rem;font-family:inherit;cursor:pointer}
button.go:disabled{opacity:.6;cursor:wait}
.err{margin-top:12px;color:var(--bad);font-weight:600}
.hidden{display:none}
/* live agents */
.feed{display:flex;flex-direction:column;gap:8px}
.msg{display:flex;gap:10px;align-items:flex-start;animation:in .25s ease}
@keyframes in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.av{flex:none;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-size:.72rem;font-weight:700;color:#fff}
.bubble{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:8px 12px;font-size:.92rem}
.bubble small{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.04em}
.a-flight{background:#2563eb}.a-stay{background:#9333ea}.a-activities{background:#ea580c}
.a-critic{background:#dc2626}.a-orchestrator{background:#0f766e}
.thinking{color:var(--muted);font-size:.9rem;padding-left:44px}
.dots::after{content:"";animation:d 1.2s steps(4,end) infinite}
@keyframes d{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}
/* result */
.head h2{font-size:1.4rem;margin-bottom:6px}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:.72rem;font-weight:600;border:1px solid var(--line)}
.pill.live{color:var(--live)}.pill.estimated{color:var(--est)}
.tips{margin:10px 0 0;padding-left:18px;color:var(--muted)}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.kv{display:flex;justify-content:space-between;gap:12px;padding:4px 0;border-bottom:1px dashed var(--line)}
.kv:last-child{border:0}.kv span:first-child{color:var(--muted)}
.big{font-size:1.5rem;font-weight:700}
.bar{display:grid;grid-template-columns:110px 1fr 90px;gap:8px;align-items:center;margin:8px 0;font-size:.88rem}
.track{position:relative;height:12px;border-radius:99px;background:var(--line);overflow:hidden}
.fill{position:absolute;inset:0 auto 0 0;border-radius:99px;background:var(--brand)}
.fill.over{background:var(--est)}
.mark{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--ink);opacity:.55}
.day{border-top:1px solid var(--line);padding:12px 0}
.day:first-child{border:0}
.day h3{margin:0 0 4px;font-size:1rem}
.note{color:var(--muted);font-size:.85rem;margin:2px 0 6px}
.item{display:grid;grid-template-columns:54px 1fr auto;gap:8px;padding:5px 0;font-size:.93rem}
.item .t{color:var(--muted);font-variant-numeric:tabular-nums}
.item .c{font-variant-numeric:tabular-nums}
.item small{color:var(--muted)}
.warn{background:var(--warn-bg);color:var(--warn);border-radius:10px;padding:8px 12px;margin:6px 0;font-size:.88rem}
.verdict{font-weight:600}
.row-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.row-actions button{padding:9px 14px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:10px;cursor:pointer;font:inherit}
#map{height:420px;border-radius:12px;border:1px solid var(--line);margin-top:8px;z-index:0}
.pin span{display:flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;color:#fff;font:700 12px system-ui;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)}
.item.meal{color:var(--muted)}
.item.meal .t{color:var(--est);font-size:.8rem}
.topbar{display:flex;justify-content:flex-end;gap:8px;align-items:center;padding-top:12px;font-size:.88rem;color:var(--muted);flex-wrap:wrap}
.topbar button,.authbox button{padding:7px 12px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:10px;cursor:pointer;font:inherit}
.authbox{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;align-items:end}
.authbox input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font:inherit}
.authmsg{margin-top:8px;font-size:.88rem;color:var(--muted)}
@media print{form,.row-actions,#live,.topbar,#auth,#saved,#history,#mapday{display:none!important}body{background:#fff}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar hidden" id="acct"></div>
  <header>
    <h1>AI Travel Planner</h1>
    <p class="sub">Tell us your budget, destination and dates. A team of agents (flights, stays, activities and a critic) plans the trip together.</p>
  </header>

  <form id="form" class="card" autocomplete="off">
    <div class="grid">
      <div><label for="destination">Destination</label><input id="destination" required value="Istanbul"></div>
      <div><label for="origin">From</label><input id="origin" value="Lahore"></div>
      <div><label for="budget">Total budget</label><input id="budget" type="number" min="1" step="any" required value="2500"></div>
      <div><label for="currency">Currency</label><input id="currency" maxlength="3" required value="USD"></div>
      <div><label for="start">Start date</label><input id="start" type="date" required></div>
      <div><label for="end">End date</label><input id="end" type="date" required></div>
      <div><label for="travelers">Travelers</label><input id="travelers" type="number" min="1" max="10" value="2"></div>
      <div><label for="style">Style</label>
        <select id="style"><option value="budget">Budget</option><option value="comfort" selected>Comfort</option><option value="luxury">Luxury</option></select></div>
      <div><label for="pace">Pace</label>
        <select id="pace"><option value="relaxed">Relaxed</option><option value="balanced" selected>Balanced</option><option value="packed">Packed</option></select></div>
      <div><label for="interests">Interests (optional)</label><input id="interests" placeholder="history, food, nature"></div>
    </div>
    <button class="go" id="go" type="submit">Plan my trip</button>
    <div class="err hidden" id="err"></div>
  </form>

  <section id="auth" class="card hidden">
    <h2>Sign in to save your trips</h2>
    <div class="authbox">
      <div><label for="email">Email</label><input id="email" type="email" autocomplete="email"></div>
      <div><label for="password">Password (min 6 characters)</label><input id="password" type="password" autocomplete="current-password"></div>
      <div class="row-actions" style="margin:0"><button type="button" id="signin">Sign in</button><button type="button" id="signup">Create account</button></div>
    </div>
    <div class="authmsg" id="authmsg"></div>
  </section>

  <section id="saved" class="card hidden"><h2>Your saved trips</h2><div id="saved-list"></div></section>

  <section id="history" class="card hidden"><h2>Your recent trips</h2><div id="hist-list"></div></section>

  <section id="live" class="card hidden">
    <h2>The agents are working</h2>
    <div class="feed" id="feed"></div>
    <div class="thinking" id="thinking"><span class="dots">Thinking</span></div>
  </section>

  <section id="result" class="hidden"></section>
</div>

<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

// sensible default dates: 30 days from now, 6 nights
(function () {
  const d = new Date(); d.setDate(d.getDate() + 30);
  const e = new Date(d); e.setDate(e.getDate() + 6);
  const f = (x) => x.toISOString().slice(0, 10);
  $("start").value = f(d); $("end").value = f(e);
})();

const AGENTS = {
  flight: ["FL", "Flight agent"], stay: ["ST", "Stay agent"], activities: ["AC", "Activities agent"],
  critic: ["CR", "Critic"], orchestrator: ["OR", "Orchestrator"],
};

function money(v, cur) {
  try { return new Intl.NumberFormat("en-US", {style: "currency", currency: cur, maximumFractionDigits: 0}).format(v); }
  catch { return Math.round(v).toLocaleString() + " " + cur; }
}
function fmtDT(iso) {
  if (!iso) return "";
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/);
  const mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return m ? `${Number(m[3])} ${mon[Number(m[2]) - 1]} ${m[4]}` : iso;
}
function hhmm(t) { return String(t || "").slice(0, 5); }
function dur(min) { return `${Math.floor(min / 60)}h ${String(min % 60).padStart(2, "0")}m`; }
function pill(src) { return `<span class="pill ${esc(src)}">${esc(src)}</span>`; }

function addStep(ev) {
  const [code, label] = AGENTS[ev.from_agent] || ["??", ev.from_agent];
  const div = document.createElement("div");
  div.className = "msg";
  div.innerHTML = `<div class="av a-${esc(ev.from_agent)}">${code}</div>
    <div class="bubble"><small>${esc(label)} &rarr; ${esc(ev.to_agent)}${ev.round ? " &middot; round " + ev.round : ""}</small>${esc(ev.text)}</div>`;
  $("feed").appendChild(div);
  div.scrollIntoView({block: "nearest", behavior: "smooth"});
}

let lastData = null;

// ---- calendar export (.ics), built in the browser ----
function icsEscape(t) { return String(t ?? "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n"); }
function icsLocal(dateStr, timeStr, addMin) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const [hh, mm] = (timeStr || "09:00:00").split(":").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d, hh, mm + (addMin || 0)));
  const p = (n) => String(n).padStart(2, "0");
  return dt.getUTCFullYear() + p(dt.getUTCMonth() + 1) + p(dt.getUTCDate()) + "T" + p(dt.getUTCHours()) + p(dt.getUTCMinutes()) + "00";
}
function buildICS(data) {
  const trip = data.trip, req = trip.request, lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI Travel Planner//EN", "CALSCALE:GREGORIAN"];
  const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  let n = 0;
  const add = (title, start, end, desc) => {
    lines.push("BEGIN:VEVENT", "UID:" + trip.trip_id + "-" + (++n) + "@ai-travel-planner", "DTSTAMP:" + stamp,
      "DTSTART:" + start, "DTEND:" + end, "SUMMARY:" + icsEscape(title), "DESCRIPTION:" + icsEscape(desc || ""), "END:VEVENT");
  };
  const f = trip.selected_flight;
  if (f) {
    const loc = (iso) => iso.slice(0, 19).replace(/[-:]/g, "");  // local wall-clock time of that airport
    add("Flight " + f.origin + " to " + f.destination, loc(f.depart_at), loc(f.arrive_at), f.airline + " (price is an estimate)");
    if (f.return_depart_at) add("Flight " + f.destination + " to " + f.origin, loc(f.return_depart_at), loc(f.return_arrive_at), f.airline);
  }
  if (trip.selected_stay) add("Stay: " + trip.selected_stay.name, icsLocal(req.start_date, "14:00:00"), icsLocal(req.start_date, "15:00:00"), "Check-in. " + trip.selected_stay.nights + " nights.");
  for (const day of trip.days) for (const it of day.items) {
    if (!it.start_time) continue;
    add(it.name, icsLocal(day.date, it.start_time), icsLocal(day.date, it.start_time, it.duration_minutes), (it.notes || "") + (it.cost ? " Est. entry " + it.cost : ""));
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}
function downloadICS(data) {
  const blob = new Blob([buildICS(data)], {type: "text/calendar"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "trip-" + data.trip.request.destination.replace(/\W+/g, "-").toLowerCase() + ".ics";
  document.body.appendChild(a); a.click(); a.remove();
}

// ---- share link: the trip itself is packed (gzip + base64url) into the URL after "#t=" ----
const b64url = (bytes) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64url = (str) => Uint8Array.from(atob(str.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
async function pipeBytes(bytes, stream) {
  const out = new Response(new Blob([bytes]).stream().pipeThrough(stream));
  return new Uint8Array(await out.arrayBuffer());
}
async function shareLink(data) {
  const btn = $("share");
  try {
    const slim = {...data, timeline: [], trip: {...data.trip, messages: [], flight_options: [], stay_options: []}};
    const packed = await pipeBytes(new TextEncoder().encode(JSON.stringify(slim)), new CompressionStream("gzip"));
    const url = location.origin + "/#t=" + b64url(packed);
    try { await navigator.clipboard.writeText(url); btn.textContent = "Link copied!"; }
    catch { window.prompt("Copy this link:", url); }
  } catch { btn.textContent = "Sharing not supported in this browser"; }
  setTimeout(() => { btn.textContent = "Copy share link"; }, 2500);
}
async function openSharedTrip() {
  if (!location.hash.startsWith("#t=")) return;
  try {
    const bytes = await pipeBytes(unb64url(location.hash.slice(3)), new DecompressionStream("gzip"));
    const data = JSON.parse(new TextDecoder().decode(bytes));
    render(data);
    $("result").scrollIntoView({behavior: "smooth"});
  } catch { showError("This share link could not be opened (it may be cut off)."); }
}

// ---- recent trips, kept in this browser only ----
const HKEY = "travel-planner-history";
function loadHistory() { try { return JSON.parse(localStorage.getItem(HKEY) || "[]"); } catch { return []; } }
function saveHistory(data) {
  try {
    const item = {at: new Date().toISOString(), data};
    const list = [item, ...loadHistory().filter((h) => h.data.trip.trip_id !== data.trip.trip_id)].slice(0, 5);
    localStorage.setItem(HKEY, JSON.stringify(list));
  } catch {}
  renderHistory();
}
function renderHistory() {
  const list = loadHistory();
  $("history").classList.toggle("hidden", !list.length);
  $("hist-list").innerHTML = list.map((h, i) => {
    const r = h.data.trip.request;
    return `<div class="kv"><span>${esc(r.destination)} &middot; ${esc(r.start_date)} to ${esc(r.end_date)} &middot; ${money(h.data.breakdown.total_cost, r.currency)}</span><button type="button" data-i="${i}" class="open-h">Open</button></div>`;
  }).join("");
  document.querySelectorAll(".open-h").forEach((b) => b.onclick = () => { render(list[Number(b.dataset.i)].data); $("result").scrollIntoView({behavior: "smooth"}); });
}
renderHistory();


// ---- load libraries only when needed ----
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const el = document.createElement("script"); el.src = src; el.onload = resolve; el.onerror = () => reject(new Error("load failed: " + src));
    document.head.appendChild(el);
  });
}
function loadCSS(href) { const l = document.createElement("link"); l.rel = "stylesheet"; l.href = href; document.head.appendChild(l); }
const LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet";
const DAY_COLORS = ["#0f766e", "#2563eb", "#9333ea", "#db2777", "#ea580c", "#65a30d", "#0891b2", "#b91c1c", "#4f46e5", "#a16207"];
let theMap = null, dayLayers = {};

async function drawMap(data) {
  const box = $("map"); if (!box) return;
  try {
    if (!window.L) { loadCSS(LEAFLET + ".min.css"); await loadScript(LEAFLET + ".min.js"); }
  } catch { box.innerHTML = '<p class="note" style="padding:12px">The map could not be loaded (check your connection).</p>'; return; }
  if (theMap) { theMap.remove(); theMap = null; }
  const c = data.center || [0, 0];
  theMap = L.map("map", {scrollWheelZoom: false}).setView(c, 12);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, attribution: "&copy; OpenStreetMap contributors"}).addTo(theMap);
  dayLayers = {};
  L.marker(c, {title: "City centre (hotel area is estimated)"}).addTo(theMap).bindPopup("<b>Stay</b><br>City centre (assumed)");
  data.trip.days.forEach((d) => {
    const group = L.layerGroup(), color = DAY_COLORS[(d.day_number - 1) % DAY_COLORS.length];
    d.items.forEach((it, idx) => {
      if (it.latitude == null || it.longitude == null) return;
      const icon = L.divIcon({className: "pin", html: `<span style="background:${color}">${idx + 1}</span>`, iconSize: [24, 24], iconAnchor: [12, 12]});
      L.marker([it.latitude, it.longitude], {icon}).bindPopup(`<b>${esc(it.name)}</b><br>Day ${d.day_number} &middot; ${hhmm(it.start_time)}`).addTo(group);
    });
    (d.meals || []).forEach((m) => {
      L.circleMarker([m.latitude, m.longitude], {radius: 6, color: "#ea580c", fillColor: "#fb923c", fillOpacity: .9, weight: 2})
        .bindPopup(`<b>${esc(m.name)}</b><br>${m.slot === "lunch" ? "Lunch" : "Dinner"} &middot; Day ${d.day_number}`).addTo(group);
    });
    dayLayers[d.day_number] = group; group.addTo(theMap);
  });
  const fit = () => {
    const pts = [];
    Object.entries(dayLayers).forEach(([n, g]) => { if (theMap.hasLayer(g)) g.eachLayer((l) => pts.push(l.getLatLng())); });
    if (pts.length) theMap.fitBounds(L.latLngBounds(pts).pad(0.15)); else theMap.setView(c, 12);
  };
  fit();
  $("mapday").onchange = () => {
    const v = $("mapday").value;
    Object.entries(dayLayers).forEach(([n, g]) => { (v === "all" || v === n) ? g.addTo(theMap) : theMap.removeLayer(g); });
    fit();
  };
  setTimeout(() => theMap && theMap.invalidateSize(), 200);
}

// ---- accounts + saved trips (Supabase; only active when the site owner has configured it) ----
let sb = null, user = null;
const SUPABASE_JS = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js";

function setUser(u) {
  user = u;
  const bar = $("acct"); bar.classList.remove("hidden");
  bar.innerHTML = u
    ? `<span>${esc(u.email)}</span><button type="button" id="signout">Sign out</button>`
    : `<button type="button" id="showauth">Sign in / Sign up</button>`;
  if (u) { $("signout").onclick = async () => { await sb.auth.signOut(); }; $("auth").classList.add("hidden"); loadSaved(); }
  else { $("showauth").onclick = () => $("auth").classList.toggle("hidden"); $("saved").classList.add("hidden"); }
}
function authMsg(t) { $("authmsg").textContent = t; }

async function initAccounts() {
  try {
    const cfg = await (await fetch("/api/config")).json();
    if (!cfg.supabase_url || !cfg.supabase_anon_key) return;
    await loadScript(SUPABASE_JS);
    sb = window.supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key);
    const {data} = await sb.auth.getSession();
    setUser(data.session ? data.session.user : null);
    sb.auth.onAuthStateChange((_e, session) => setUser(session ? session.user : null));
    if (lastData) $("save").classList.remove("hidden");
    $("signin").onclick = async () => {
      authMsg("Signing in...");
      const {error} = await sb.auth.signInWithPassword({email: $("email").value.trim(), password: $("password").value});
      authMsg(error ? error.message : "");
    };
    $("signup").onclick = async () => {
      authMsg("Creating account...");
      const {data: d, error} = await sb.auth.signUp({email: $("email").value.trim(), password: $("password").value});
      if (error) authMsg(error.message);
      else authMsg(d.session ? "" : "Account created. Check your email to confirm it, then sign in.");
    };
  } catch (e) { console.warn("accounts unavailable", e); }
}

function slimForSave(data) {
  return {...data, timeline: [], trip: {...data.trip, messages: [], flight_options: [], stay_options: []}};
}
async function saveTrip(data) {
  if (!user) { $("auth").classList.remove("hidden"); $("auth").scrollIntoView({behavior: "smooth"}); authMsg("Sign in first, then press Save trip again."); return; }
  const r = data.trip.request, btn = $("save");
  btn.disabled = true; btn.textContent = "Saving...";
  const {error} = await sb.from("trips").insert({
    destination: r.destination, start_date: r.start_date, end_date: r.end_date,
    total_cost: data.breakdown.total_cost, currency: r.currency, data: slimForSave(data)});
  btn.textContent = error ? "Could not save" : "Saved!";
  if (error) console.warn(error); else loadSaved();
  setTimeout(() => { btn.disabled = false; btn.textContent = "Save trip"; }, 2500);
}
async function loadSaved() {
  if (!sb || !user) return;
  const {data, error} = await sb.from("trips").select("id,created_at,destination,start_date,end_date,total_cost,currency")
    .order("created_at", {ascending: false}).limit(30);
  if (error) { console.warn(error); return; }
  $("saved").classList.toggle("hidden", !data.length);
  $("saved-list").innerHTML = data.map((t) => `<div class="kv"><span>${esc(t.destination)} &middot; ${esc(t.start_date)} to ${esc(t.end_date)} &middot; ${money(t.total_cost, t.currency)}</span>
    <span><button type="button" class="open-s" data-id="${esc(t.id)}">Open</button> <button type="button" class="del-s" data-id="${esc(t.id)}">Delete</button></span></div>`).join("");
  document.querySelectorAll(".open-s").forEach((b) => b.onclick = async () => {
    const {data: row, error: e2} = await sb.from("trips").select("data").eq("id", b.dataset.id).single();
    if (!e2 && row) { render(row.data); $("result").scrollIntoView({behavior: "smooth"}); }
  });
  document.querySelectorAll(".del-s").forEach((b) => b.onclick = async () => {
    if (!confirm("Delete this saved trip?")) return;
    await sb.from("trips").delete().eq("id", b.dataset.id); loadSaved();
  });
}

function render(data) {
  const t = data.trip, req = t.request, cur = req.currency, br = data.breakdown;
  const src = data.data_sources || {};
  const flight = t.selected_flight, stay = t.selected_stay;

  const bars = br.lines.map((l) => {
    const max = Math.max(l.planned, l.actual, 1);
    const over = l.delta > 0 && l.category !== "unspent";
    const label = l.category === "unspent" ? "Left over" : l.category.replace("_", " + ");
    return `<div class="bar"><span style="text-transform:capitalize">${esc(label)}</span>
      <div class="track"><div class="fill ${over ? "over" : ""}" style="width:${(l.actual / max * 100).toFixed(1)}%"></div>
      <div class="mark" style="left:${(l.planned / max * 100).toFixed(1)}%" title="planned"></div></div>
      <span style="text-align:right">${money(l.actual, cur)}</span></div>`;
  }).join("");

  const days = t.days.map((d) => {
    const items = d.items.map((i) => `<div class="item"><span class="t">${hhmm(i.start_time)}</span>
      <span>${esc(i.name)}<br><small>${esc(i.category)} &middot; ${i.duration_minutes} min${i.area ? " &middot; " + esc(i.area) : ""}</small></span>
      <span class="c">${i.cost > 0 ? money(i.cost, cur) : "Free"}</span></div>`).join("");
    const meals = (d.meals || []).map((m) => `<div class="item meal"><span class="t">${m.slot === "lunch" ? "Lunch" : "Dinner"}</span>
      <span>${esc(m.name)}<br><small>${esc(m.cuisine || "restaurant")}${m.area ? " &middot; " + esc(m.area) : ""}${m.matches_diet === true ? " &middot; matches your diet" : m.matches_diet === false ? " &middot; diet not confirmed" : ""}</small></span>
      <span class="c">${/^https?:\/\//.test(m.website || "") ? `<a href="${esc(m.website)}" target="_blank" rel="noopener noreferrer">website</a>` : ""}</span></div>`).join("");
    return `<div class="day"><h3>Day ${d.day_number} &middot; ${esc(d.date)}</h3>
      ${d.notes ? `<div class="note">${esc(d.notes)}</div>` : ""}${items || ""}${meals}</div>`;
  }).join("");

  const warns = (data.review.warnings || []).map((w) => `<div class="warn">${esc(w)}</div>`).join("");
  const tips = (data.summary.tips || []).map((x) => `<li>${esc(x)}</li>`).join("");
  const srcPills = Object.entries(src).map(([k, v]) => `${esc(k.replace("_", " "))} ${pill(v)}`).join(" &nbsp; ");

  $("result").innerHTML = `
  <div class="card head">
    <h2>${esc(data.summary.headline || "Your trip")}</h2>
    <p style="margin:0 0 8px">${esc(data.summary.overview)}</p>
    <div><span class="big">${money(br.total_cost, cur)}</span> <span class="sub">of ${money(br.budget, cur)} budget &middot; ${br.within_budget ? "within budget" : "OVER budget"} &middot; ${data.rounds} negotiation round(s)</span></div>
    ${tips ? `<ul class="tips">${tips}</ul>` : ""}
  </div>
  <div class="two">
    <div class="card"><h2>Flight ${flight ? pill(flight.source) : ""}</h2>${flight ? `
      <div class="kv"><span>Airline</span><span>${esc(flight.airline)}</span></div>
      <div class="kv"><span>Outbound</span><span>${fmtDT(flight.depart_at)} &rarr; ${fmtDT(flight.arrive_at)}</span></div>
      <div class="kv"><span>Return</span><span>${fmtDT(flight.return_depart_at)} &rarr; ${fmtDT(flight.return_arrive_at)}</span></div>
      <div class="kv"><span>Stops &middot; duration</span><span>${flight.stops} &middot; ${dur(flight.duration_minutes)}</span></div>
      <div class="kv"><span>Total (all travelers)</span><b>${money(flight.total_price, cur)}</b></div>` : "<p>No flight selected.</p>"}</div>
    <div class="card"><h2>Stay ${stay ? pill(stay.source) : ""}</h2>${stay ? `
      <div class="kv"><span>Name</span><span>${esc(stay.name)}</span></div>
      <div class="kv"><span>Area</span><span>${esc(stay.area || "-")}</span></div>
      <div class="kv"><span>Per night &middot; nights</span><span>${money(stay.price_per_night, cur)} &middot; ${stay.nights}</span></div>
      <div class="kv"><span>Includes</span><span>${esc((stay.amenities || []).join(", "))}</span></div>
      <div class="kv"><span>Total</span><b>${money(stay.total_price, cur)}</b></div>` : "<p>No stay selected.</p>"}</div>
  </div>
  <div class="card"><h2>Budget breakdown</h2>${bars}
    <div class="note">Bar = actual cost. Dark line = planned share.</div>
    <div class="verdict">${esc(data.review.verdict || "")}</div>${warns}</div>
  <div class="card"><h2>Map</h2>
    <select id="mapday"><option value="all">All days</option>${t.days.filter((d) => d.items.length || (d.meals || []).length).map((d) => `<option value="${d.day_number}">Day ${d.day_number}</option>`).join("")}</select>
    <div id="map"></div><div class="note">Numbers = sights in order (colour = day). Orange dots = suggested restaurants. The hotel pin sits at the city centre because hotel locations are estimated.</div></div>
  <div class="card"><h2>Day by day</h2>${days}</div>
  <div class="card"><h2>Data sources</h2><div class="note">Live = fetched from a real provider now. Estimated = typical prices, check before booking.</div>${srcPills}
    <div class="row-actions"><button type="button" id="save" class="hidden">Save trip</button><button type="button" id="share">Copy share link</button><button type="button" id="ics">Add to calendar (.ics)</button><button type="button" id="print">Print / save as PDF</button><button type="button" id="again">Plan another trip</button></div></div>`;
  $("result").classList.remove("hidden");
  $("print").onclick = () => window.print();
  $("ics").onclick = () => downloadICS(data);
  $("share").onclick = () => shareLink(data);
  if (sb) { $("save").classList.remove("hidden"); $("save").onclick = () => saveTrip(data); }
  drawMap(data);
  lastData = data;
  $("again").onclick = () => { $("result").classList.add("hidden"); $("live").classList.add("hidden"); window.scrollTo({top: 0, behavior: "smooth"}); };
}

function parseSSE(buffer, onEvent) {
  let idx;
  while ((idx = buffer.indexOf("\n\n")) >= 0) {
    const block = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
    let ev = "message", data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) ev = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (data) { try { onEvent(ev, JSON.parse(data)); } catch (e) { console.error(e); } }
  }
  return buffer;
}

function showError(msg) {
  $("err").textContent = msg; $("err").classList.remove("hidden");
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("err").classList.add("hidden"); $("result").classList.add("hidden");
  $("feed").innerHTML = ""; $("live").classList.remove("hidden"); $("thinking").classList.remove("hidden");
  $("go").disabled = true; $("go").textContent = "Planning...";
  const interests = $("interests").value.split(",").map((s) => s.trim()).filter(Boolean);
  const body = {
    budget: Number($("budget").value), currency: $("currency").value.trim(), destination: $("destination").value.trim(),
    origin: $("origin").value.trim() || null, start_date: $("start").value, end_date: $("end").value,
    travelers: Number($("travelers").value) || 1,
    preferences: {style: $("style").value, pace: $("pace").value, interests},
  };
  let got = false;
  try {
    const res = await fetch("/api/plan/stream", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    if (!res.ok) {
      let detail = "Request failed (" + res.status + ").";
      try { const j = await res.json(); detail = Array.isArray(j.detail) ? j.detail.map((d) => d.msg).join("; ") : (j.detail || detail); } catch {}
      throw new Error(detail);
    }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buf = parseSSE(buf + dec.decode(value, {stream: true}).replace(/\r\n/g, "\n"), (ev, data) => {
        if (ev === "step") addStep(data);
        else if (ev === "result") { got = true; render(data); saveHistory(data); $("thinking").classList.add("hidden"); $("result").scrollIntoView({behavior: "smooth"}); }
        else if (ev === "error") { got = true; showError(data.detail || "Planning failed."); $("thinking").classList.add("hidden"); }
      });
    }
    if (!got) throw new Error("The connection closed before the plan was ready. Please try again.");
  } catch (err) {
    showError(err.message || String(err)); $("thinking").classList.add("hidden");
  } finally {
    $("go").disabled = false; $("go").textContent = "Plan my trip";
  }
});
openSharedTrip();
initAccounts();
</script>
</body>
</html>
"""
