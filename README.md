# Noxen

> AI agent that transforms existing codebases — no migrations, no rewrites, directly on production code.

Noxen understands your codebase, plans improvements, and implements them through Claude Code — with your approval at every step.

**You own the code. You own the API keys. Noxen provides the intelligence.**

## How it works

1. **Spider Analysis** — reads and understands your codebase
2. **Research** — finds best practices for your stack
3. **Board Planning** — multiple LLMs deliberate and plan
4. **Your Approval** — you review before anything is touched
5. **Execution** — Claude Code implements in isolated sandbox
6. **Review and Merge** — you see the diff, you decide

## Requirements

> **Internet connection is required.**
> Noxen uses internet for LLM providers, license validation, and Research Agent.
> Noxen will not start without internet access.

- Internet connection (required)
- Docker and Docker Compose
- At least one LLM API key (Anthropic Claude, Google Gemini, or OpenAI)
- Claude Code CLI (optional, for code execution)
  Install: `npm install -g @anthropic-ai/claude-code`

## Quick Start

```bash
git clone https://github.com/noxen-ai/noxen
cd noxen
cp .env.example .env
# edit .env with your API keys
docker-compose up -d
open http://localhost:8400
```

## Configuration

Minimum `.env` to start:

```
NOXEN_GEMINI_API_KEY=your-key-here
```

See `.env.example` for all options.

## Licensing

Licensed under **Business Source License 1.1**.

**Free for:** personal use, evaluation, non-commercial projects, single-organization self-hosted deployments.

**Requires license for:** commercial SaaS, multi-tenant deployments.

Converts to Apache 2.0 on January 1, 2030.

Commercial licensing: https://noxen.ai/pricing

## On-Premise vs Cloud

**On-premise** (free, BSL): Set `NOXEN_MULTITENANT_ENABLED=false` (default). Single tenant, no auth required, unlimited use for your organization.

**Cloud** (noxen.ai): Managed SaaS, multi-tenant, SSO, audit logs.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). BSL license applies to contributions.
