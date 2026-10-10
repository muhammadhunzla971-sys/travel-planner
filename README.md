# AI Travel Planner (Multi-Agent)

Customer gives budget, destination and dates. An orchestrator coordinates flight, stay and
activities agents and returns a complete trip plan. Runs fully online (no local heavy services).

## Progress
- [x] Step 1: skeleton + health endpoint, deployed on Vercel
- [x] Step 2: data models, TripState, message protocol, budget allocator
- [ ] Step 3: provider adapters (flights, hotels, places, currency, weather) + cache + mock fallback

## Endpoints (so far)
- `GET /health`
- `GET /version`
- `GET /docs` (Swagger UI)
- `POST /api/budget/preview` (validate a trip request and see the budget split)

## Run the tests (optional, needs Python)
```
cd backend
pip install -r requirements-dev.txt
pytest
```
