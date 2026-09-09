# Router AI — Multi-provider LLM gateway + Chat workspace

Router is a Python-first **AI routing engine** that puts multiple model providers behind one resilient interface. It automatically handles provider failures, rate limits, cooldowns, circuit breaking and usage tracking so an application can keep responding when one provider is unavailable.

## ✨ Interactive web workspace

The repository includes a dependency-free, ChatGPT-style web workspace under `web/`, backed by `server.py`.

### What the UI includes

- 💬 Multi-turn conversational chat with incremental streaming
- 🔀 Automatic model/provider routing and failover
- 🧠 Model picker populated from configured providers
- 🔐 Account registration/login with HttpOnly sessions
- 👤 Server-side conversation and analytics isolation per user
- 📚 Recent conversation history
- 📋 Copy and regenerate actions
- 📊 Live provider/usage status panel
- ⚙ Runtime settings view
- 📱 Responsive mobile layout with collapsible sidebar
- ⌨️ Enter-to-send and Shift+Enter for multiline prompts
- 🔒 Provider API keys stay server-side in `.env`; the browser never receives them
- 🔑 Project-scoped `rtr_live_...` API keys with hashed-at-rest storage and revocation
- 📈 Per-project daily request/token quotas and usage metering
- 🧩 Same Router core and Skills system used by the CLI

## Architecture

```text
Browser (Chat UI)
       │  HttpOnly session cookie
       ▼
   server.py ─────── SQLite users/sessions/workspaces
       │
       ├──────────── Project API keys + quotas + usage events
       ▼
    Router
   /  |  |  \
  /   |  |   \
OpenRouter Groq Gemini Cerebras Mistral HuggingFace
```

The web layer is intentionally thin: routing, retries, failover, provider health and token accounting remain in the Python core. Project API keys are stored as SHA-256 hashes; the raw secret is returned only when the key is created.

## Providers

The built-in catalog supports OpenRouter, Cerebras, Groq, Gemini, Mistral and Hugging Face. Only providers with configured API keys are activated.

## Installation

```bash
python3 --version
python3 -m unittest discover -s tests -v
```

No external Python framework is required for the web server.

## Configuration

Copy `.env.example` to `.env` and add the API keys you want to use. Configure provider ordering with `PROVIDER_PRIORITY` and optional retry behavior with `ROUTER_MAX_RETRIES`.

Web authentication is enabled by default. Useful settings:

- `ROUTER_AUTH_REQUIRED=1` — require accounts for the workspace (recommended)
- `ROUTER_SESSION_TTL_SECONDS=604800` — session lifetime; default 7 days
- `ROUTER_COOKIE_SECURE=1` — send the session cookie only over HTTPS in production
- `ROUTER_CORS_ORIGIN=https://your-domain.example` — explicit origin when using cross-origin deployments
- `ROUTER_WEB_DB=/data/router_web.sqlite3` — persistent SQLite database location
- `ROUTER_MAX_BODY_BYTES=1048576` — maximum JSON request size
- `ROUTER_RATE_LIMIT=30` and `ROUTER_RATE_WINDOW_SECONDS=60` — basic per-IP API throttling

Passwords are stored as salted PBKDF2-SHA256 hashes and session tokens are stored only as SHA-256 hashes. Never commit `.env` or real provider API keys.

## Launch the web app

```bash
python3 server.py
```

Open `http://127.0.0.1:8080` in your browser and create an account.

For a LAN development session:

```bash
HOST=0.0.0.0 PORT=8080 python3 server.py
```

For production, use HTTPS and set `ROUTER_COOKIE_SECURE=1` plus an explicit `ROUTER_CORS_ORIGIN`.

## API

### Health

`GET /api/health` — public liveness endpoint.

### Authentication

- `GET /api/auth/me`
- `POST /api/auth/register` with `{ "email": "...", "password": "..." }`
- `POST /api/auth/login` with `{ "email": "...", "password": "..." }`
- `POST /api/auth/logout`

Passwords must be at least 10 characters. Authenticated browser endpoints use the HttpOnly `router_session` cookie.

### Projects and API keys

Projects and key-management endpoints use the browser session:

- `GET /api/projects`
- `GET /api/projects/{project_id}`
- `POST /api/projects` with optional `name`, `requests_per_day`, and `tokens_per_day`
- `GET /api/projects/{project_id}/keys`
- `POST /api/projects/{project_id}/keys` with optional `name`
- `DELETE /api/projects/{project_id}/keys/{key_id}` — revoke a key
- `DELETE /api/projects/{project_id}` — delete a project and its keys

Creating a key returns the raw `rtr_live_...` secret once. Store it securely; subsequent key listings expose only the prefix and metadata.

### API-key access

`POST /api/chat` accepts either the browser session or:

```http
Authorization: Bearer rtr_live_...
```

A valid project key authenticates the request to its owning project. The project daily request quota is checked before the request, and successful/failed calls are recorded with model, provider, token counts and latency.

For a project-scoped key, `GET /api/usage/{project_id}` returns the current usage report. The project ID must match the authenticated key's project.

### Authenticated workspace

- `GET /api/status`
- `GET /api/skills`
- `GET /api/conversations`
- `GET /api/conversations/{id}`
- `POST /api/conversations`
- `DELETE /api/conversations/{id}`
- `GET /api/analytics`
- `POST /api/chat`

Chat requests support streaming with `"stream": true`; the response uses incremental SSE-style events followed by `[DONE]`.

## CLI

```bash
python -m llmrouter.cli "Explícame qué es una red neuronal en 2 frases"
python -m llmrouter.cli "Este texto es muy largo..." --skill summarize
```

## Project structure

```text
.
├── server.py              # Web API + static file server + auth + API keys
├── web/
│   ├── index.html         # Auth + chat workspace
│   ├── styles.css         # Responsive UI
│   └── app.js             # Client state and interactions
├── llmrouter/
│   ├── core/              # Routing, providers, errors, usage
│   ├── providers/         # Provider catalog/adapters
│   ├── skills/            # Extensible skills/plugins
│   ├── api_keys.py        # Projects, API keys, quotas and usage metering
│   └── web_store.py       # SQLite users, sessions, conversations, analytics
└── tests/                 # Automated tests
```

## Production roadmap

- [x] Streaming responses with safe pre-output failover
- [x] Persistent server-side conversations
- [x] Authentication and per-user workspace isolation
- [x] Basic usage analytics and rate limiting
- [x] API keys per project with quotas and billing-ready usage events
- [ ] Bind browser chat to selectable projects and expose project controls in the UI
- [ ] Advanced request tracing and observability
- [ ] File uploads and document/RAG workflows
- [ ] Tool calling and agent orchestration
- [ ] Model playground / side-by-side comparison
- [ ] Production deployment templates and API documentation

## License

MIT