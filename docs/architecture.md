# Architecture

## Components

- `Ollama`: local inference for chat, summarization, and consolidation
- `AnythingLLM Desktop`: primary chat UI and retrieval layer running as a Windows desktop application
- `AnythingLLM LanceDB`: default local vector store for workspace retrieval inside the desktop app
- `n8n`: automation engine
- `SearXNG`: local/private current-events retrieval
- `Shared local storage`: readable context and memory artifacts
- `Qdrant` (optional): only needed later if you want a standalone shared vector service across multiple apps

## Storage layout

Root:

- `local-ai-data/assistant-memory/`

Folders:

- `context/`
- `memory/`
- `inbox/raw/`
- `inbox/processed/`
- `archive/`
- `backups/`
- `logs/`

Core files:

- `memory/identity_and_preferences.md`
- `memory/current_projects.md`
- `memory/active_decisions.md`
- `memory/environment_and_tools.md`
- `memory/recent_context_summary.md`
- `context/daily_world_context.md`
- `context/runtime_context.md`

## Retrieval strategy

- In the desktop app, keep AnythingLLM on its default local `LanceDB` vector database.
- The authoritative source remains the local markdown files under `local-ai-data/assistant-memory/`.
- n8n is responsible for pushing changed files into AnythingLLM through its local API.
- Use `/api/v1/document/upload` or `/api/v1/document/upload/{folderName}` to register changed documents.
- Use `/api/v1/workspace/{slug}/update-embeddings` to refresh the workspace vectors after uploads.
- Exclude `archive/` and `inbox/` from default retrieval to avoid noise.
- Treat `memory/` as authoritative durable context.
- Treat `context/` as time-sensitive current context.
- Treat `Qdrant` as optional future infrastructure, not part of the baseline design.

## Data flow

### Chat

1. User chats in the AnythingLLM desktop app.
2. AnythingLLM retrieves from its local LanceDB workspace store.
3. Ollama answers locally using retrieved context.

### Memory capture

1. User submits a note to an n8n webhook.
2. n8n stores the raw note in `inbox/raw/`.
3. Ollama classifies and summarizes it.
4. n8n updates the relevant curated memory file.
5. n8n uploads the changed file to AnythingLLM.
6. n8n calls `update-embeddings` for the workspace.

### Current events

1. n8n queries SearXNG on a schedule.
2. Results are deduplicated and summarized by Ollama.
3. n8n writes `context/daily_world_context.md`.
4. n8n uploads the refreshed file to AnythingLLM.
5. n8n calls `update-embeddings` for the workspace.

### Runtime context

1. n8n writes current date/time on a short schedule.
2. The assistant uses `context/runtime_context.md` instead of guessing.
3. Runtime context is excluded from API-driven embedding refresh by default because high-frequency updates create unnecessary embedding churn.

### Consolidation

1. n8n reviews the current memory files weekly.
2. Ollama compresses duplicates and refreshes summaries.
3. n8n writes back cleaner versions and archives notes.
4. n8n uploads the rewritten curated files to AnythingLLM.
5. n8n calls `update-embeddings` once after the batch completes.

## Workflow assets

Import the n8n workflow exports from `n8n-workflows/`.

## Security assumptions

- All core processing is local by default.
- Services should be exposed only to localhost, LAN, or VPN as needed.
- Cloud LLM APIs are not required for baseline operation.
- The AnythingLLM desktop app should be configured to use local Ollama and local retrieval sources only.
- Protect the AnythingLLM API key because n8n will use it for document upload and embedding refresh.
- Outbound traffic still exists for container pulls, software updates, model downloads, and SearXNG's upstream searches.