# Laval Digital — AI Marketing Agency Platform

A full-stack AI marketing automation platform for small-to-medium businesses. Built with a multi-agent LangGraph orchestration engine, multi-tenant database isolation, bilingual public pages (EN/FR), affiliate/reseller programs, and an automated client deployment pipeline (Client Factory).

## Architecture

- **Multi-Agent System**: 11 specialized agents (Local SEO, Social Media, Lead Conversion, Paid Ads, Growth Hacker, Reputation, Email Marketing, TikTok, Outreach, Backlinks, Executioner)
- **Orchestrator**: LangGraph-based workflow routing with human-in-the-loop approval via interrupts
- **Multi-Tenant**: Database-per-tenant isolation — direct clients at `/tenants/direct/<id>.db`, resellers at `/tenants/resellers/<id>/`
- **Bilingual**: All public pages served in English and French (`/fr/` routes)
- **Client Factory**: 7-station automated deploy pipeline (validate → subdomain → tenant DB → clone template → inject brand → Nginx → SSL → welcome email)
- **Admin Panel**: Tabbed sidebar layout (Dashboard, Agents, Tasks & Approvals, Deploy Client, Settings) with tenant selector, inline agent toggle, and execution management
- **Affiliate Engine**: Session-based referral tracking with 30-day persistent cookie and $500 discount
- **Reseller Program**: Founding Partner offers with wholesale pricing tiers
- **Contract Flow**: Package selector, milestone-based payments, digital signature, Interac e-Transfer instructions

## Tech Stack

- **Backend**: Python 3.12+, Flask, gunicorn (`-w 1 --threads 4`)
- **AI Framework**: LangChain + LangGraph
- **LLM Providers**: DeepSeek, OpenAI, Anthropic (via LiteLLM)
- **Database**: SQLite (database-per-tenant)
- **Templating**: Jinja2
- **Deployment**: Client Factory with Nginx + Certbot SSL provisioning

## Project Structure

```
laval-digital/
├── app.py                    # Flask application — all routes, API endpoints, agent registry
├── client_factory.py         # Automated client deployment pipeline (7 stations)
├── core/
│   ├── base_agent.py         # BaseAgent abstract class
│   ├── orchestrator.py       # LangGraph orchestration engine
│   ├── llm_adapter.py        # Multi-LLM adapter (DeepSeek/OpenAI/Anthropic)
│   └── tenant_manager.py     # Database-per-tenant lifecycle (8 tables, 11-agent seeding)
├── agents/                   # Specialized agent implementations
│   ├── local_seo_agent.py
│   ├── social_media_agent.py
│   ├── lead_conversion_agent.py
│   ├── paid_ads_agent.py
│   ├── growth_hacker_agent.py
│   ├── reputation_agent.py
│   ├── email_marketing_agent.py
│   ├── tiktok_agent.py
│   ├── outreach_agent.py
│   ├── backlinks_agent.py
│   └── executioner_agent.py  # Executes approved drafts via SMTP/social APIs
├── tools/
│   └── prospect_scraper.py   # Google Maps Places API prospect scraper + CSV export
├── prompts/                  # System prompt templates for each agent
├── templates/                # Jinja2 templates
│   ├── home.html / home_fr.html
│   ├── contract.html / contract_fr.html
│   ├── affiliate.html / affiliate_fr.html
│   ├── reseller.html / reseller_fr.html
│   ├── admin.html / admin_fr.html
│   ├── demo.html / demo_fr.html
│   ├── blog.html / blog_fr.html
│   ├── login.html / login_fr.html
│   └── lead_site.html        # Client lead site template with brand injection
├── static/                   # Static assets (CSS, JS, logos)
├── config/
│   └── client_config.json    # Default client configuration
├── tenants/                  # Tenant database storage
│   ├── direct/               # Direct client databases
│   └── resellers/            # Reseller tenant databases
├── data/
│   └── prospects/            # CSV export directory for prospect scraper
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
   GOOGLE_MAPS_API_KEY=your-maps-key   # optional — scraper falls back to sample data
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
| `/api/contract/submit` | POST | Submit a signed agreement |
| `/api/reseller/apply` | POST | Submit a reseller application |
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
| `/api/clients/deploy` | POST | Deploy a new client via Client Factory |

## Pricing Tiers

| Package | Base Price | With Affiliate Discount |
|---|---|---|
| Core | $8,500/mo | $8,000/mo |
| Growth | $12,500/mo | $12,000/mo |
| Full Empire | $16,500/mo | $16,000/mo |

Affiliate commission: 10% of discounted package price. Referring friend gets $500 off.

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
