# Laval Digital — Frankie AI Marketing Command Center

Frankie is a standalone AI marketing command center that connects to your existing website, social accounts, email, and ad platforms. 16 specialized AI agents work 24/7 to grow your business. One product. One price. No website builder, no subdomain, no payment schedules.

## Architecture

- **Multi-Agent System**: 16 specialized agents (Local SEO, Social Media, Lead Conversion, Paid Ads, Growth Hacker, Reputation, Email Marketing, TikTok, Outreach, Backlinks, Content Strategy, Technical SEO, CRO, Video, SMS Marketing, Analytics & Reports)
- **Frankie Orchestrator**: LangGraph-based workflow routing with human-in-the-loop approval via interrupts
- **Multi-Tenant**: Database-per-tenant isolation at `/tenants/direct/<id>.db`
- **Bilingual**: All public pages served in English and French (`/fr/` routes)
- **Admin Panel**: Tabbed sidebar layout (Dashboard, Agents, Tasks & Approvals, Settings, Users, Analytics, Reports) with tenant selector, inline agent toggle, agent config, and execution management
- **Affiliate Referrals**: Lightweight 20% commission tracking with session-based referral cookies

## Tech Stack

- **Backend**: Python 3.12+, Flask, gunicorn (`-w 1 --threads 4`)
- **AI Framework**: LangChain + LangGraph
- **LLM Providers**: DeepSeek, OpenAI, Anthropic (via LiteLLM)
- **Database**: SQLite (database-per-tenant)
- **Templating**: Jinja2
- **Frontend**: PWA dashboard (installable on any device)

## Project Structure

```
laval-digital/
├── app.py                    # Flask application — all routes, API endpoints, agent registry
├── core/
│   ├── base_agent.py         # BaseAgent abstract class
│   ├── orchestrator.py       # LangGraph orchestration engine
│   ├── llm_adapter.py        # Multi-LLM adapter (DeepSeek/OpenAI/Anthropic)
│   ├── auth.py               # Authentication, user management, role handling
│   ├── tenant_manager.py     # Database-per-tenant lifecycle
│   └── analytics.py          # Per-tenant analytics and reporting
├── agents/                   # 16 specialized agent implementations
│   ├── local_seo_agent.py
│   ├── social_media_agent.py
│   ├── lead_conversion_agent.py
│   ├── paid_ads_agent.py
│   ├── growth_hacker_agent.py
│   ├── reputation_agent.py
│   ├── email_marketing_agent.py
│   ├── tiktok_agent.py
│   ├── outreach_agent.py
│   └── backlinks_agent.py
├── tools/
│   └── prospect_scraper.py   # Google Maps Places API prospect scraper + CSV export
├── prompts/                  # System prompt templates for each agent
├── templates/                # Jinja2 templates
│   ├── home.html / home_fr.html
│   ├── admin.html / admin_fr.html
│   ├── demo.html / demo_fr.html
│   ├── blog.html / blog_fr.html
│   ├── login.html / login_fr.html
│   └── affiliate.html / affiliate_fr.html
├── static/                   # Static assets (CSS, JS, logos)
├── tenants/direct/           # Per-tenant SQLite databases
├── data/
│   └── vapid_keys.json       # Web push notification keys
└── requirements.txt
```

## Quick Start

1. **Clone and install**:
   ```bash
   git clone https://github.com/shogodel/laval-digital.git
   cd laval-digital
   pip install -r requirements.txt
   ```

2. **Configure environment** (create `.env`):
   ```
   DEEPSEEK_API_KEY=sk-your-deepseek-key
   FLASK_SECRET_KEY=your-random-secret
   ADMIN_USERNAME=laval
   ADMIN_PASSWORD=digital2026!
   GOOGLE_MAPS_API_KEY=your-maps-key
   ```

3. **Run the server**:
   ```bash
   gunicorn -w 1 --threads 4 --daemon app:app
   ```
   Access at `http://127.0.0.1:5000`. Admin panel at `/admin`.

   > **Note:** Jinja2 template caching is active in gunicorn production mode. Kill the gunicorn master process (`pkill -f gunicorn`) and restart for template changes to take effect.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/affiliate/status` | GET | Return affiliate discount status for current session |
| `/api/affiliate/signup` | POST | Register a new affiliate, return referral code |
| `/api/leads` | GET/POST | List or create lead form submissions |
| `/api/agents` | GET | List all agents with activity telemetry |
| `/api/agents/<id>/toggle` | POST | Enable/disable an agent |
| `/api/agents/<id>/config` | GET/POST | Get or update agent configuration |
| `/api/agents/<id>/invoke` | POST | Directly invoke an agent (bypass orchestrator) |
| `/api/tasks` | POST | Submit a task to the orchestrator |
| `/api/approvals` | GET | Get pending approvals |
| `/api/approvals/<id>/respond` | POST | Approve or reject a pending approval |
| `/api/executioner/settings` | GET/PUT | Get or update executioner settings |
| `/api/executioner/pending` | GET | Get executions awaiting confirmation |
| `/api/executioner/confirm/<id>` | POST | Confirm and execute a queued execution |
| `/api/executioner/reject/<id>` | POST | Reject a queued execution |
| `/api/executions` | GET | Get recent execution history |
| `/api/models` | GET | List available LLM models |
| `/api/models/detect` | POST | Detect provider from API key |
| `/api/tenants` | GET | List all tenants (admin only) |
| `/api/tenants/switch` | POST | Switch admin active tenant context |
| `/api/users` | GET/POST | List or create users for active tenant |
| `/api/users/<id>` | DELETE | Delete a user |
| `/api/personalities` | GET | Get agent personalities/emojis |
| `/api/agents/bulk/config` | POST | Bulk update agent configurations |

## Pricing

**$597.99/month** — All 16 AI agents + Frankie command center. One product. One price.

## Agent Configuration

Each agent expects a config in this format:

```json
{
  "agent_id": "local_seo",
  "enabled": true,
  "model": "deepseek-chat",
  "system_prompt_file": "prompts/local_seo.md",
  "credentials": {
    "api_key": "sk-...",
    "api_base": "https://api.deepseek.com/v1"
  }
}
```

## License

MIT
