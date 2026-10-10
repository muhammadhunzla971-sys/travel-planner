# AI Travel Planner (Multi-Agent)

Customer gives budget, destination and dates. An orchestrator coordinates flight, stay and
activities agents and returns a complete trip plan. Runs fully online (no local heavy services).

## Progress
- [x] Step 1: skeleton + health endpoint, deployed on Vercel
- [x] Step 2: data models, TripState, message protocol, budget allocator
- [x] Step 3: provider adapters (flights, hotels, places, currency, weather) + cache + mock fallback
- [x] Step 4: agents (flight, stay, activities, critic) + Groq LLM client with fallbacks
- [ ] Step 5: orchestrator + negotiation loop

## Endpoints (so far)
- `GET /health`
- `GET /version`
- `GET /docs` (Swagger UI)
- `POST /api/budget/preview` (validate a trip request and see the budget split)
- `POST /api/tools/preview` (live data: geocode, FX, weather, attractions + estimated flights/stays)
- `GET /api/llm/check` (is the Groq key set and working? never shows the key)
- `POST /api/agents/preview` (one pass of all agents + critic; negotiation comes in Step 5)

## Environment variables
`GROQ_API_KEY` (secret, set only in Vercel). Optional: `LLM_MODEL`, `LLM_FALLBACK_MODEL`, `LLM_ENABLED`, `LLM_TIMEOUT_S`.
Without a key the agents still work using rule-based logic.

## Run the tests (optional, needs Python)
```
cd backend
pip install -r requirements-dev.txt
pytest
```
