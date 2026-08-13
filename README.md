# RooomRoute — Explainable Multi-LLM Router

Version: `0.3.0-alpha`

RooomRoute is a source-available multi-LLM router that makes routing decisions using quality, cost, latency, failure state, data classification, region, capabilities, and provider correlation. It exposes OpenAI-compatible Chat Completions and Responses APIs and can route across vLLM, NVIDIA NIM, TGI, Ollama, and cloud LLM endpoints.

## Differentiators

- **Sovereignty Lattice** — policy gates for public/internal/confidential/restricted data
- **Transparent Route Receipt** — selected candidates, exclusions, scores, cost, latency, and execution path
- **Adaptive Topology** — direct, cascade, draft/verify, and parallel consensus
- **Correlated-error Defense** — provider diversity for consensus paths
- **Continuous Bandit Learning** — feedback affects subsequent routing without waiting for an offline retrain
- **Hard Policy Gates** — region, capability, context, cost, and latency constraints before scoring
- **Counterfactual Planning** — inspect the planned route without calling an LLM
- **Air-gap First** — supports disconnected OpenAI-compatible inference endpoints

Sakana Fugu is used as one public comparison baseline. RooomRoute does not claim general benchmark superiority until both systems are tested under comparable conditions. See `docs/FUGU_COMPARISON.md`.

## Quick start

```bash
docker compose up --build
```

Or with Python 3.11+:

```bash
cp router.example.json router.json
PYTHONPATH=src python -m rooomtech_router --config router.json
```

The legacy Python import path `rooomtech_router` is retained during the `0.3.x` line for compatibility; the product and distribution name are RooomRoute / `rooom-route`.

## API

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/models`
- `POST /v1/route/plan`
- `GET /v1/routes/{route_id}`
- `POST /v1/feedback`
- `GET /healthz` / `GET /readyz`
- `GET /metrics`

## Security

Route Receipts and SQLite audit state do not store prompt/response bodies by default. HMAC signing, API-key authentication, request data classification, and air-gapped endpoints are supported. See `SECURITY.md`.

## Licensing and enterprise support

Starting with version `0.3.0`, ROOOMTECH-authored code is available under the terms described in `LICENSE`: PolyForm Noncommercial License 1.0.0 for permitted noncommercial uses, or a separate paid ROOOMTECH Commercial Software License for business/commercial-purpose uses outside those permissions.

Commercial license agreements, maintenance, technical support, implementation, integration, upgrades, security support, SLA options, private builds, and custom development are available.

Contact: `support@rooomtech.com`

Earlier releases retain their published license terms. Third-party software retains its own licenses.
