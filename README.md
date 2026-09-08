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
- 🔒 API keys stay server-side in `.env`; the browser never receives them
- 🧩 Same Router core and Skills system used by the CLI

## Architecture

```text
Browser (Chat UI)
       │  HttpOnly session cookie
       ▼
   server.py ─────── SQLite users/sessions/workspaces
       │
       ▼
    Router
   /  |  |  \
  /   |  |   \
OpenRouter Groq Gemini Cerebras Mistral HuggingFace
```

The web layer is intentionally thin: routing, retries, failover, provider health and token accounting remain in the Python core.

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

Passwords are stored as salted PBKDF2-SHA256 hashes and session tokens are stored only as SHA-256 hashes. Never commit `.env` or real API keys.

## Launch the web app

```bash
python3 server.py
```

Open `http://127.0.0.1:8080` in your browser and create an account.

For a LAN development session:

```bash
HOST=0.0.0.0 PORT=8080 python3 server.py
```

For production, use HTTPS and set `ROUTER_COOKIE_SECURE=1`.

## API

### Health

`GET /api/health` — public liveness endpoint.

### Authentication

- `GET /api/auth/me`
- `POST /api/auth/register` with `{ "email": "...", "password": "..." }`
- `POST /api/auth/login` with `{ "email": "...", "password": "..." }`
- `POST /api/auth/logout`

Passwords must be at least 10 characters. Authenticated endpoints use the HttpOnly `router_session` cookie.

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
├── server.py              # Web API + static file server + auth
├── web/
│   ├── index.html         # Auth + chat workspace
│   ├── styles.css         # Responsive UI
│   └── app.js             # Client state and interactions
├── llmrouter/
│   ├── core/              # Routing, providers, errors, usage
│   ├── providers/         # Provider catalog/adapters
│   ├── skills/             # Extensible skills/plugins
│   └── web_store.py       # SQLite users, sessions, conversations, analytics
└── tests/                 # Automated tests
```

## Production roadmap

- [x] Streaming responses with safe pre-output failover
- [x] Persistent server-side conversations
- [x] Authentication and per-user workspace isolation
- [x] Basic usage analytics and rate limiting
- [ ] API keys per user/project with quotas and billing-ready metering
- [ ] Advanced request tracing and observability
- [ ] File uploads and document/RAG workflows
- [ ] Tool calling and agent orchestration
- [ ] Model playground / side-by-side comparison
- [ ] Production deployment templates and API documentation

## License

MIT
