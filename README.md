# AI Travel Planner (Multi-Agent)

A customer enters a **budget, destination and dates**. A team of agents plans the whole trip together and
shows the negotiation live:

- **Flight agent**, **Stay agent**, **Activities agent** each propose within their share of the budget
- **Critic** checks the plan with deterministic code (budget, night arrivals, overlaps) - the LLM can never approve a bad plan
- **Orchestrator** runs research, collects proposals, and lets the agents negotiate (max 4 rounds) until the plan fits

Live site: the root URL of the Vercel deployment (`/`). Free to run, no credit card, nothing runs on your PC.

## How it works
```
Browser (/)  --POST /api/plan/stream-->  FastAPI on Vercel
                                           |
                    Orchestrator --research--> Open-Meteo (geocode, weather), FX rates, Wikipedia (attractions)
                        |  proposals
        Flight agent / Stay agent / Activities agent  <--LLM (Groq gpt-oss) picks among validated options
                        |
                      Critic (rules)  --objection--> Orchestrator --constraint--> agents re-propose
                        |
              final plan + budget breakdown + timeline  --SSE-->  Browser
```
- Flights and hotels have no free keyless price API, so they are **estimates and always labelled** `estimated`.
- Destination, FX rate, attractions and (near-term) weather are **live**. Every number shows its source.
- If the LLM or any provider fails, rule-based fallbacks keep the planner working.

## Features
- Live agent conversation (Server-Sent Events), budget bars, day-by-day plan
- Add to calendar (.ics), print / save as PDF, **shareable link** (the trip is packed into the URL), recent trips (stored in your browser)
- **Map** (Leaflet + OpenStreetMap): numbered sights per day, restaurants, day filter
- **Restaurants**: lunch/dinner suggestions near each day's sights (OpenStreetMap data); honours dietary needs such as halal / vegetarian when OSM confirms them
- **Accounts + saved trips** (optional, Supabase free plan): sign up, save, reopen and delete trips. Setup: `docs/supabase_schema.sql`,
  then set `SUPABASE_URL` and `SUPABASE_ANON_KEY` in Vercel
- 193 automated tests, GitHub Actions CI (`ruff` + `pytest`)

## Endpoints
- `GET /` website, `GET /docs` Swagger, `GET /health`, `GET /version`
- `POST /api/plan` full planner, `POST /api/plan/stream` same with live progress (SSE)
- `POST /api/budget/preview`, `POST /api/tools/preview`, `POST /api/agents/preview` (step-by-step debugging)
- `GET /api/places/debug?city=Istanbul` shows what Wikipedia returned and why places were kept or dropped
- `GET /api/config` public site settings (accounts on/off, never secrets)
- `GET /api/llm/check` is the Groq key working? (never shows the key)

## Environment variables
`GROQ_API_KEY` (secret, set only in Vercel). Optional: `LLM_MODEL` (default `openai/gpt-oss-120b`),
`LLM_FALLBACK_MODEL` (`openai/gpt-oss-20b`), `LLM_ENABLED`, `LLM_TIMEOUT_S`. Without a key the agents use rules only.

## Run the tests (optional)
```
cd backend
pip install -r requirements-dev.txt
ruff check . && pytest -q
```

## Demo script (2 minutes)
1. Open the site, keep Istanbul / 2500 USD, press **Plan my trip**.
2. Point at the live feed: the Critic objects to a 04:13 arrival, the Orchestrator tells the Flight agent, a daytime flight is chosen.
3. Show the budget bars (planned share vs actual) and the **estimated / live** labels.
4. Try a tiny budget (e.g. 300 USD) to show the "infeasible budget" handling.
5. Press **Copy share link**, open it in a new tab, then export the **.ics** to a calendar.

## Known limits
- Flight and hotel prices are estimates (no free live fare API). Check before booking.
- Restaurant data has no prices or ratings (OpenStreetMap); meal costs stay inside the "food + transport" estimate.
- Serverless memory cache is best-effort; Vercel Hobby has a function time limit (planning normally takes 5-20 s).

## Ideas for later
Real flight/hotel API (Amadeus/Duffel free tiers need sign-up), hotel locations on the map, editing a trip (drag to reorder),
sharing a saved trip with friends.
