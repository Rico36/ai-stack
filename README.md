# Local AI Assistant Platform

This repository turns a local AI stack into a privacy-first personal assistant platform with local inference, readable long-term memory files, private search, and n8n automation.

## Included

- `docker-compose.yml`
- `deploy/docker-compose.local-ai.yml`
- `.env.example`
- `docs/architecture.md`
- `docs/operations.md`
- `prompts/anythingllm-system-prompt.md`
- `local-ai-data/assistant-memory/`
- `n8n-workflows/`

## Recommended flow

1. Use `docker-compose.yml` as the base stack.
2. Optionally layer `deploy/docker-compose.local-ai.yml` on top if you are merging this into another compose deployment.
3. Copy `.env.example` to `.env` and set the stack-level secrets and paths you actually use.
4. Start the stack with `docker compose up -d`, or use your merged compose command if you are applying the overlay.
5. Import the JSON files from `n8n-workflows/` into n8n.
6. In AnythingLLM Desktop, create or choose a workspace that uses the default local `LanceDB` vector store.
7. Point AnythingLLM to your local Ollama instance.
8. Apply `prompts/anythingllm-system-prompt.md` as workspace instructions or your system prompt.
9. Use the memory capture webhook for durable facts and decisions.

## Important configuration note

This repo no longer treats `.env` as the source of truth for the imported n8n workflows.

The compose stack still reads `.env` for container-level settings like:

- `LOCAL_AI_DATA_ROOT`
- `TZ`
- `N8N_*`
- database and app secrets
- optional AnythingLLM-related pass-through variables

But the workflow exports in `n8n-workflows/` currently contain their own node-level configuration. After importing them into n8n, review and update these values inside the workflows or credentials:

- AnythingLLM API credential named `AnythingLLM API Key`
- AnythingLLM base URL, currently `http://host.docker.internal:3001`
- workspace slug, currently `my-assistant`
- memory capture token placeholder in `personal-memory-capture.json`
- Ollama model names, currently hardcoded to `qwen3:14b`
- runtime workflow timezone, currently hardcoded to `America/New_York`

In other words: update workflow settings in n8n, not just `.env`, when you change workflow behavior.

## n8n workflows

The `n8n-workflows/` folder contains four baseline workflows:

- `runtime-context-refresh.json`
  Refreshes `runtime_context.md` on a short schedule so the assistant has the correct date, time, timezone, and timestamp instead of guessing.
- `daily-world-context-refresh.json`
  Queries SearXNG for recent news, deduplicates results, summarizes them with Ollama, and writes `daily_world_context.md`.
- `personal-memory-capture.json`
  Accepts a user note through a webhook, stores the raw note in `inbox/raw/`, summarizes and classifies it with Ollama, then updates the appropriate curated memory file.
- `weekly-memory-consolidation.json`
  Reviews the curated memory files on a schedule, reduces duplication, refreshes summaries, and writes cleaner long-term memory back to disk.

Current behavior in the exported workflows:

- `runtime-context-refresh.json`: scheduled every 15 minutes
- `daily-world-context-refresh.json`: scheduled every 6 hours
- `weekly-memory-consolidation.json`: scheduled weekly
- `personal-memory-capture.json`: webhook-triggered, not scheduled

## AnythingLLM ingestion strategy

The preferred model is API-driven ingestion instead of manual workspace re-sync.

n8n can call these AnythingLLM Desktop endpoints after files change:

- `/api/v1/document/upload`
- `/api/v1/document/upload/{folderName}`
- `/api/v1/workspace/{slug}/update-embeddings`

Recommended event-driven behavior:

- Upload changed durable memory files after the memory capture workflow updates them.
- Upload `daily_world_context.md` after the news workflow finishes.
- Upload the rewritten curated memory files after weekly consolidation completes.
- Avoid re-embedding `runtime_context.md` on every 15-minute refresh unless you explicitly want that churn.

Recommended sequence:

1. n8n writes or updates the local markdown files.
2. n8n uploads the changed file or files to AnythingLLM.
3. n8n calls `/api/v1/workspace/{slug}/update-embeddings`.
4. AnythingLLM refreshes the workspace embeddings in local LanceDB.

Manual fallback:

- If the API path is unavailable, open the AnythingLLM workspace and run sync or re-embed manually.

## Core principle

Raw chat logs are history, not authoritative memory. Durable context lives in curated markdown files under `local-ai-data/assistant-memory/`.
