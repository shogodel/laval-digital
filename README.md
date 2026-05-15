# Frankie — AI Marketing Command Center

Frankie is a standalone AI marketing command center that connects to your existing website, social accounts, email, and ad platforms. 16 specialized AI agents work 24/7 to grow your business. One product. One price. No website builder, no subdomain, no payment schedules.

## Architecture

- **Multi-Agent System**: 16 specialized agents (Local SEO, Social Media, Lead Conversion, Paid Ads, Growth Hacker, Reputation, Email Marketing, TikTok, Outreach, Backlinks, Content Strategy, Technical SEO, CRO, Video, SMS Marketing, Analytics & Reports)
- **Frankie Orchestrator**: LangGraph-based workflow routing with human-in-the-loop approval via interrupts
- **MCP Server Layer**: 8 MCP servers (111 tools) for real platform execution — SEO, Social, Email, GMB, Ads, Analytics, Website, E-Commerce
- **MCP-First Execution**: Every execution path (chat, approvals, direct invoke, executioner) tries MCP servers first, falls back to file-based tools
- **Multi-Tenant**: Database-per-tenant isolation at `/tenants/direct/<id>.db` with per-tenant MCP credential storage
- **Bilingual**: All public pages served in English and French (`/fr/` routes)
- **Admin Panel**: Tabbed sidebar layout (Dashboard, Agents, Tasks & Approvals, Settings, Users, Analytics, Reports, MCP Servers) with tenant selector, inline agent toggle, agent config, MCP credential management, and execution management
- **Affiliate Referrals**: Lightweight 20% commission tracking with session-based referral cookies

## Tech Stack

- **Backend**: Python 3.12+, Flask, gunicorn (`-w 1 --threads 4`)
- **AI Framework**: LangChain + LangGraph
- **LLM Providers**: DeepSeek, OpenAI, Anthropic (via LiteLLM)
- **MCP Protocol**: Custom MCP server implementation with tool registry, credential management, and auto-routing
- **Database**: SQLite (database-per-tenant)
- **Templating**: Jinja2
- **Frontend**: PWA dashboard (installable on any device)

## Project Structure

```
laval-digital/
├── app.py                    # Flask application — all routes, API endpoints, agent registry, MCP wiring
├── core/
│   ├── base_agent.py         # BaseAgent abstract class
│   ├── orchestrator.py       # LangGraph orchestration engine
│   ├── llm_adapter.py        # Multi-LLM adapter (DeepSeek/OpenAI/Anthropic)
│   ├── auth.py               # Authentication, user management, role handling
│   ├── tenant_manager.py     # Database-per-tenant lifecycle + MCP credentials table
│   └── analytics.py          # Per-tenant analytics and reporting
├── mcp/                      # 8 MCP servers (111 tools total)
│   ├── base_server.py        # MCPServer base class with tool registry
│   ├── __init__.py           # Server registry and initialization
│   ├── seo_server.py         # SEO & Content — blog publishing, site audit, schema, backlinks (13 tools)
│   ├── social_server.py      # Social Media — Facebook, Instagram, TikTok, LinkedIn, X (18 tools)
│   ├── email_server.py       # Email Marketing — campaigns, sequences, automation (16 tools)
│   ├── gmb_server.py         # Google Business Profile — posts, reviews, Q&A (16 tools)
│   ├── ads_server.py         # Paid Advertising — Google Ads, Meta Ads, TikTok Ads (18 tools)
│   ├── analytics_server.py   # Analytics & Reporting — ROI, trends, dashboards, executive summary (12 tools)
│   ├── website_server.py     # Website Technical — uptime, SSL, DNS, security, SEO scanning (18 tools)
│   └── ecommerce_server.py   # E-Commerce — products, inventory, pricing, RFM, Shopify/WooCommerce (15 tools)
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
│   ├── backlinks_agent.py
│   ├── content_strategy_agent.py
│   ├── technical_seo_agent.py
│   ├── reporting_agent.py
│   ├── cro_agent.py
│   ├── video_agent.py
│   ├── sms_marketing_agent.py
│   └── executioner_agent.py  # MCP-first execution engine with file-based fallback
├── tools/
│   └── prospect_scraper.py   # Google Maps Places API prospect scraper + CSV export
├── prompts/                  # System prompt templates for each agent
├── templates/                # Jinja2 templates
│   ├── home.html / home_fr.html
│   ├── admin.html / admin_fr.html
│   ├── demo.html / demo_fr.html
│   ├── blog.html / blog_fr.html
│   ├── login.html / login_fr.html
│   ├── affiliate.html / affiliate_fr.html
│   ├── admin/
│   │   ├── agent_chat.html / agent_chat_fr.html
│   │   └── connector.html
│   └── client/
│       ├── agent_chat.html / agent_chat_fr.html
│       ├── dashboard.html
│       └── login.html
├── static/                   # Static assets (CSS, JS, logos, PWA)
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

### Core & Agents

| Endpoint | Method | Description |
|---|---|---|
| `/api/affiliate/status` | GET | Return affiliate discount status for current session |
| `/api/affiliate/signup` | POST | Register a new affiliate, return referral code |
| `/api/leads` | GET/POST | List or create lead form submissions |
| `/api/agents` | GET | List all agents with activity telemetry |
| `/api/agents/<id>/toggle` | POST | Enable/disable an agent |
| `/api/agents/<id>/config` | GET/POST | Get or update agent configuration |
| `/api/agents/<id>/invoke` | POST | Directly invoke an agent (bypass orchestrator) |
| `/api/agents/<id>/chat` | POST | Send a message directly to a specific agent |
| `/api/tasks` | POST | Submit a task to the orchestrator |
| `/api/approvals` | GET | Get pending approvals |
| `/api/approvals/<id>/respond` | POST | Approve or reject a pending approval |
| `/api/models` | GET | List available LLM models |
| `/api/models/detect` | POST | Detect provider from API key |
| `/api/tenants` | GET | List all tenants (admin only) |
| `/api/tenants/switch` | POST | Switch admin active tenant context |
| `/api/users` | GET/POST | List or create users for active tenant |
| `/api/users/<id>` | DELETE | Delete a user |
| `/api/personalities` | GET | Get agent personalities/emojis |
| `/api/agents/bulk/config` | POST | Bulk update agent configurations |

### MCP Servers

| Endpoint | Method | Description |
|---|---|---|
| `/api/mcp/servers` | GET | List all MCP servers and their status |
| `/api/mcp/servers/<name>/tools` | GET | List all tools for a specific MCP server |
| `/api/mcp/call` | POST | Call a tool on an MCP server directly |
| `/api/mcp/execute` | POST | Execute via MCP with auto agent-to-server routing |
| `/api/mcp/credentials` | GET | Get stored MCP credentials for current tenant |
| `/api/mcp/credentials` | POST | Save MCP credentials for current tenant |
| `/api/mcp/credentials/<server>` | DELETE | Delete credentials for an MCP server |

### Executioner (Fallback)

| Endpoint | Method | Description |
|---|---|---|
| `/api/executioner/settings` | GET/PUT | Get or update executioner settings |
| `/api/executioner/pending` | GET | Get executions awaiting confirmation |
| `/api/executioner/confirm/<id>` | POST | Confirm and execute a queued execution |
| `/api/executioner/reject/<id>` | POST | Reject a queued execution |
| `/api/executioner/execute-chat` | POST | Execute via file-based tools (legacy) |
| `/api/executions` | GET | Get recent execution history |

### Analytics & Speech

| Endpoint | Method | Description |
|---|---|---|
| `/api/analytics/summary` | GET | Summary analytics for tenant or all tenants |
| `/api/analytics/leads` | GET | Lead metrics for date range |
| `/api/analytics/agents` | GET | Agent performance metrics |
| `/api/analytics/executions` | GET | Execution metrics |
| `/api/analytics/report/generate` | POST | Generate monthly report HTML |
| `/api/speech/stt` | POST | Transcribe audio to text |
| `/api/speech/tts` | POST | Synthesize speech from text |
| `/api/speech/voices` | GET | List available TTS voices |

## MCP Server Tool Inventory

| Server | Tools | Key Capabilities |
|---|---|---|
| **SEO** (13) | publish_blog_post, run_site_audit, generate_schema, find_backlink_opportunities, ... | WordPress/Webflow/Shopify CMS integration, site crawling, schema markup, backlink prospecting |
| **Social** (18) | post_to_facebook, post_to_instagram, post_to_tiktok, post_to_linkedin, post_to_x, ... | Multi-platform publishing, content calendars, hashtag generation, engagement tracking |
| **Email** (16) | send_email, send_campaign, create_sequence, design_automation, ... | SMTP/SendGrid/Mailgun integration, campaign management, drip sequences |
| **GMB** (16) | create_gmb_post, respond_to_review, manage_qa, update_hours, ... | Google Business Profile posts, review management, business info updates |
| **Ads** (18) | create_google_ads_campaign, create_meta_ads, optimize_bidding, ... | Google Ads, Meta Ads, TikTok Ads campaign creation and optimization |
| **Analytics** (12) | track_roi, analyze_trends, compare_periods, get_executive_summary, get_chart_data, ... | DB-driven ROI from tenant data, trend analysis, period comparison, executive summaries |
| **Website** (18) | monitor_uptime, check_page_speed, manage_ssl, security_scan, dns_lookup, ... | Real HTTP scanning, SSL verification, DNS lookups, security header checks, sitemap validation |
| **E-Commerce** (15) | manage_products, track_inventory, optimize_product_pages, analyze_customers, ... | Shopify/WooCommerce API, RFM segmentation, live page auditing, pricing optimization, Canadian taxes |

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

Every execution path — chat Execute button, admin approval flow, direct agent invoke, and the ExecutionerAgent itself — tries MCP servers first before falling back to the original file-based tools.

## Agent-to-MCP Routing

| Agent | MCP Server | Default Tool |
|---|---|---|
| local_seo | seo | publish_blog_post |
| social_media | social | post_to_facebook |
| lead_conversion | email | send_email |
| paid_ads | ads | create_google_ads_campaign |
| growth_hacker | analytics | analyze_trends |
| reputation | gmb | respond_to_review |
| email_marketing | email | send_campaign |
| tiktok | social | post_to_tiktok |
| outreach | email | send_email |
| backlinks | seo | find_backlink_opportunities |
| content_strategist | seo | publish_blog_post |
| technical_seo | seo | run_site_audit |
| reporting | analytics | generate_monthly_report |
| cro | website | audit_seo_health |
| video | social | post_to_tiktok |
| sms_marketing | email | send_email |

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
