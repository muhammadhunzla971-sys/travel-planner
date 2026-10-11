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
@media print{form,.row-actions,#live{display:none!important}body{background:#fff}}
</style>
</head>
<body>
<div class="wrap">
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
  return m ? `${m[3]}/${m[2]} ${m[4]}` : iso;
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
    return `<div class="day"><h3>Day ${d.day_number} &middot; ${esc(d.date)}</h3>
      ${d.notes ? `<div class="note">${esc(d.notes)}</div>` : ""}${items || ""}</div>`;
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
  <div class="card"><h2>Day by day</h2>${days}</div>
  <div class="card"><h2>Data sources</h2><div class="note">Live = fetched from a real provider now. Estimated = typical prices, check before booking.</div>${srcPills}
    <div class="row-actions"><button type="button" id="ics">Add to calendar (.ics)</button><button type="button" id="print">Print / save as PDF</button><button type="button" id="again">Plan another trip</button></div></div>`;
  $("result").classList.remove("hidden");
  $("print").onclick = () => window.print();
  $("ics").onclick = () => downloadICS(data);
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
</script>
</body>
</html>
"""
