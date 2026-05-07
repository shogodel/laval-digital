# Laval Digital - AI Marketing Automation for SMBs

A multi-agent LangGraph system designed for small business marketing automation. Built for local businesses (plumbers, electricians, contractors) to automate their digital marketing workflows.

## Architecture

- **Multi-Agent System**: Specialized agents for Local SEO, Social Media/Content, and Lead Conversion
- **Orchestrator**: Coordinates agent workflows and task routing
- **Human-in-the-Loop**: All agent actions require human approval via LangGraph interrupts
- **Multi-LLM Support**: Switch between DeepSeek, GPT-4o, and Claude 3.5 Sonnet
- **Per-Agent Configuration**: Individual API keys, model selection, and on/off toggles

## Tech Stack

- **Backend**: Python 3.12+ with Flask
- **AI Framework**: LangChain + LangGraph
- **LLM Providers**: DeepSeek, OpenAI, Anthropic (via LiteLLM)
- **Checkpointing**: MemorySaver for state persistence

## Project Structure

```
laval-digital/
├── core/
│   └── base_agent.py      # BaseAgent class for all agents
├── agents/                 # Specialized agent implementations
├── tools/                  # LangChain tools for agents
├── config/                 # Agent configurations
├── prompts/                # System prompt templates
├── templates/              # Flask templates
├── static/                 # Static assets
├── scripts/                # Utility scripts
└── requirements.txt        # Python dependencies
```

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure agents** in `config/` with your API keys and preferences

3. **Run the system**:
   ```bash
   python -m core.base_agent
   ```

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

## Supported Models

- `deepseek-chat` - DeepSeek Chat
- `gpt-4o` - OpenAI GPT-4o
- `claude-3.5-sonnet` - Anthropic Claude 3.5 Sonnet

## License

MIT
