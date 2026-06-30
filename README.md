# Laval Digital — AI Marketing Command Center for Shopify

AI-powered marketing automation for Shopify stores. 16 specialized AI agents work 24/7 to grow your business. One product. One price. **$23.99/month**.

## Architecture

- **Multi-Agent System**: 16 specialized agents (Local SEO, Social Media, Lead Conversion, Paid Ads, Growth Hacker, Reputation, Email Marketing, TikTok, Outreach, Backlinks, Content Strategy, Technical SEO, CRO, Video, SMS Marketing, Analytics & Reports) with specialized subclasses (`CreativeAgent`, `AnalyticalAgent`, `SalesAgent`, `BaseAgent`) and per-agent temperature control
- **AI Orchestrator**: Agent workflow routing with LLM-based agent selection, draft generation, approval, and execution — source-aware prompts (`widget` vs `chat`)
- **MCP Server Layer**: 8 MCP servers (111 tools) for real platform execution — SEO, Social, Email, GMB, Ads, Analytics, Website, E-Commerce
- **MCP-First Execution**: Every execution path (chat, approvals, direct invoke, executioner) tries MCP servers first, falls back to file-based tools
- **Database**: SQLite (dev) or PostgreSQL (prod) via `DATABASE_URL` env var with Alembic migrations, connection pooling (`DB_POOL_MIN`/`DB_POOL_MAX`), and gevent-compatible psycopg2
- **Multi-Store**: Multiple Shopify stores linked by owner email, with store switcher in admin UI
- **Custom Agent Name**: Every store can name their AI assistant (stored in `shops.agent_name`)
- **Bilingual**: All public pages served in English and French (`/fr/` routes)
- **Admin Panel**: Shopify Embedded App with dashboard, agent management, approvals, settings, analytics, MCP credential management
- **Event Bus**: Pub/sub event system for real-time UI updates via SSE
- **Structured Logging**: JSON log format with correlation IDs (`request_id`), PII redaction, and key rotation fingerprint

## Tech Stack

- **Backend**: Python 3.12+, Flask, gunicorn (`-w 1 --worker-class gevent --worker-connections 1000`)
- **AI Framework**: LangChain + LiteLLM (DeepSeek, OpenAI, Anthropic, Gemini, Mistral)
- **Database**: SQLite (dev) / PostgreSQL 15+ (prod) via Alembic migrations
- **Async**: Gevent (monkey-patched at bootstrap) with psycogreen for cooperative psycopg2
- **Encryption**: Fernet (cryptography) with HKDF/PBKDF2 domain separation (credential, Shopify token, VAPID subsystems)
- **Templating**: Jinja2 with CSP nonces
- **Frontend**: PWA dashboard (installable on any device), WebSocket-free SSE event streaming

## Project Structure

```
laval-digital/
├── app.py                    # Flask application factory, routes, agent registry, MCP wiring
├── core/
│   ├── settings.py           # App-wide config, agent definitions, PII redaction, encryption helpers
│   ├── base_agent.py         # BaseAgent + CreativeAgent, AnalyticalAgent, SalesAgent subclasses
│   ├── app_state.py          # Module-level singletons populated at boot time
│   ├── database.py           # Dual-backend (SQLite/PostgreSQL) with connection pool
│   ├── orchestrator.py       # LangGraph orchestration engine
│   ├── llm_adapter.py        # Multi-LLM adapter with circuit breaker and rate limiting
│   ├── auth.py               # Authentication, User/AdminUser models, session management
│   ├── shopify_auth.py       # Shopify OAuth, session tokens, HMAC validation
│   ├── analytics.py          # Per-tenant analytics and reporting
│   ├── events.py             # Pub/sub event bus with SSE streaming
│   ├── push.py               # Web push notification manager
│   ├── monitor.py            # Proactive monitoring agent
│   ├── scheduler.py          # Scheduled task manager
│   ├── memory.py             # Agent memory and findings board
│   ├── rate_limiter.py       # IP-based and user-based rate limiting
│   ├── email_bridge.py       # Email sending via SMTP
│   └── speech.py             # TTS/STT speech engine
├── agents/
│   └── executioner_agent.py  # MCP-first execution engine with file-based fallback
├── mcp/                      # 8 MCP servers (111 tools total)
│   ├── base_server.py        # MCPServer base class with tool registry
│   ├── __init__.py           # Server registry and initialization
│   ├── seo_server.py         # SEO & Content (13 tools)
│   ├── social_server.py      # Social Media (18 tools)
│   ├── email_server.py       # Email Marketing (16 tools)
│   ├── gmb_server.py         # Google Business Profile (16 tools)
│   ├── ads_server.py         # Paid Advertising (18 tools)
│   ├── analytics_server.py   # Analytics & Reporting (12 tools)
│   ├── website_server.py     # Website Technical (18 tools)
│   └── ecommerce_server.py   # E-Commerce / Shopify (15 tools)
├── blueprints/               # Flask blueprints for all route groups
├── migrations/               # Alembic migrations
├── prompts/                  # System prompt templates for each agent
├── templates/                # Jinja2 templates
├── static/                   # Static assets (CSS, JS, logos, PWA)
├── tests/                    # 188 tests across 11 test files
├── tools/
│   └── prospect_scraper.py   # Google Maps Places API prospect scraper
├── Dockerfile                # Gevent worker config
├── alembic.ini               # Alembic configuration
├── .env.example
└── pyproject.toml
```

## Quick Start

1. **Clone and install**:
   ```bash
   git clone https://github.com/shogodel/laval-digital.git
   cd laval-digital
   pip install -r requirements.txt
   ```

2. **Configure environment** (copy `.env.example` to `.env`):
   ```
   FLASK_SECRET_KEY=<generate-with: python -c "import secrets; print(secrets.token_hex(32))">
   SHOPIFY_API_KEY=<your-shopify-api-key>
   SHOPIFY_API_SECRET=<your-shopify-api-secret>
   SHOPIFY_APP_HOME=https://your-domain.com
   ```

3. **Initialize the database**:
   ```bash
   python -c "from core import database; database.init_db()"
   ```

4. **Run the server** (development):
   ```bash
   python app.py
   ```
   Access at `http://127.0.0.1:5000`.

   **Production** (Docker):
   ```bash
   docker build -t laval-digital .
   docker run -p 5000:5000 --env-file .env laval-digital
   ```

## Database Backends

Set `DATABASE_URL` to switch between SQLite and PostgreSQL:

| `DATABASE_URL` | Backend |
|---|---|
| `sqlite:///data/shopify.db` | SQLite (dev default) |
| `postgresql://user:pass@host:5432/dbname` | PostgreSQL (production) |

Optional pool config for PostgreSQL: `DB_POOL_MIN=1`, `DB_POOL_MAX=10`.

## Pricing

**$23.99/month** — All 16 AI agents + command center. One product. One price.

## API Endpoints

### Core

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check (DB, LLM, encryption) |
| `/api/tasks` | POST | Submit a task to the orchestrator |
| `/api/approvals` | GET | Get pending approvals |
| `/api/approvals/<id>/respond` | POST | Approve or reject a pending approval |
| `/api/agents` | GET | List all agents with activity telemetry |
| `/api/agents/<id>/toggle` | POST | Enable/disable an agent |
| `/api/agents/<id>/config` | GET/POST | Get or update agent configuration |
| `/api/agents/<id>/autonomy` | GET/PUT | Get/set autonomy level |
| `/api/agents/<id>/invoke` | POST | Directly invoke an agent |
| `/api/agents/<id>/chat` | POST | Chat with an agent (SSE streaming) |
| `/api/agents/bulk/config` | POST | Bulk update all agent configurations |
| `/api/models` | GET | List available LLM models |
| `/api/models/detect` | POST | Detect provider from API key |
| `/api/personalities` | GET | Get agent personalities/emojis |

### Chat & Dashboard

| Endpoint | Method | Description |
|---|---|---|
| `/api/dashboard/ask` | POST | Widget-style quick ask (source="widget") |
| `/api/orchestrator/welcome` | POST | Get welcome message |
| `/api/orchestrator/suggestions` | POST | Get task suggestions |
| `/api/orchestrator/status` | GET | Panic status, pending count |
| `/api/orchestrator/activity` | GET | Activity feed |
| `/api/orchestrator/panic` | POST | Emergency stop all agents |
| `/api/orchestrator/resume` | POST | Resume agents after panic |
| `/api/orchestrator/undo` | POST | Undo last execution |
| `/api/inbox` | GET | Combined approvals + activity |
| `/api/threads` | GET | List conversation threads |
| `/api/threads/<tid>/messages` | GET | Get thread messages |
| `/api/executions` | GET | Recent execution history |

### MCP Servers

| Endpoint | Method | Description |
|---|---|---|
| `/api/mcp/servers` | GET | List all MCP servers |
| `/api/mcp/servers/<name>/tools` | GET | List tools for an MCP server |
| `/api/mcp/call` | POST | Call an MCP tool directly |
| `/api/mcp/execute` | POST | Execute via MCP with auto-routing |
| `/api/mcp/credentials` | GET/POST | Get or save MCP credentials |
| `/api/mcp/credentials/<server>` | DELETE | Delete MCP credentials |

### Shopify

| Endpoint | Method | Description |
|---|---|---|
| `/api/auth/install` | GET | Shopify OAuth install redirect |
| `/api/auth/callback` | GET | Shopify OAuth callback |
| `/api/webhooks` | POST | Shopify webhook receiver |
| `/api/shopify/register-webhooks` | POST | Register webhook subscriptions |
| `/api/shopify/products` | GET | List Shopify products |
| `/api/shopify/orders` | GET | List Shopify orders |

### Analytics & Speech

| Endpoint | Method | Description |
|---|---|---|
| `/api/analytics/summary` | GET | Summary analytics |
| `/api/analytics/leads` | GET | Lead metrics |
| `/api/analytics/agents` | GET | Agent performance metrics |
| `/api/analytics/executions` | GET | Execution metrics |
| `/api/analytics/report/generate` | POST | Generate monthly report |
| `/api/speech/stt` | POST | Transcribe audio |
| `/api/speech/tts` | POST | Synthesize speech |
| `/api/speech/voices` | GET | List TTS voices |

### Users & GDPR

| Endpoint | Method | Description |
|---|---|---|
| `/api/user/export` | GET | Export all personal data (GDPR) |
| `/api/user/export` | DELETE | Erase all personal data (right to erasure) |
| `/api/users` | GET/POST | List or create users |
| `/api/users/<id>` | DELETE | Delete a user |

### Events (SSE)

| Endpoint | Method | Description |
|---|---|---|
| `/api/events/stream` | GET | SSE event stream (real-time) |
| `/api/events/history` | GET | Event history with filters |
| `/api/events/stats` | GET | Event bus statistics |

## Execution Flow

```
User Request → Orchestrator → Agent generates draft → Human approves
                                                        ↓
                                              /api/approvals/<id>/respond
                                                        ↓
                                              MCP-First Execution
                                              ┌─────────────────┐
                                              │ Try MCP Server  │──success──→ Return result
                                              │ (auto-routed)   │
                                              └────────┬────────┘
                                                       │ failed/no mapping
                                                       ↓
                                              Executioner Fallback
                                              (file-based tools)
```

## Agent Configuration

Each agent expects a config in this format (set via admin UI or bulk API):

```json
{
  "agent_id": "local_seo",
  "enabled": true,
  "model": "deepseek-chat",
  "temperature": 0.6,
  "system_prompt_file": "prompts/local_seo.md",
  "credentials": {
    "api_key": "sk-...",
    "api_base": "https://api.deepseek.com/v1"
  }
}
```

## License

MIT
