# Operations Guide

## Deployment

1. Keep your current compose stack as the base deployment.
2. Add `deploy/docker-compose.local-ai.yml` as an overlay for `n8n` and shared storage.
3. Set values from `deploy/.env.example` in your real `.env`.
4. Start or recreate the updated services.
5. Import the workflows from `n8n-workflows/` into n8n.
6. In the AnythingLLM desktop app at `C:\Users\Ricky\AppData\Local\Programs\AnythingLLM\AnythingLLM.exe`, create a workspace.
7. Keep AnythingLLM on its default local `LanceDB` vector database unless you intentionally choose an external store later.
8. Point AnythingLLM to your local Ollama instance.
9. Create or identify the target workspace slug and generate an AnythingLLM API key.
10. Put these values in your real `.env` for n8n:
   - `ANYTHINGLLM_API_BASE`
   - `ANYTHINGLLM_API_KEY`
   - `ANYTHINGLLM_WORKSPACE_SLUG`
   - `ANYTHINGLLM_UPLOAD_FOLDER`
   - `ANYTHINGLLM_SYNC_RUNTIME_CONTEXT`
11. Apply the prompt in `prompts/anythingllm-system-prompt.md` as workspace instructions or your system prompt.

## AnythingLLM API-driven sync

The preferred sync path is through AnythingLLM Desktop's API:

- document upload: `/api/v1/document/upload`
- document upload to a named folder: `/api/v1/document/upload/{folderName}`
- workspace embedding refresh: `/api/v1/workspace/{slug}/update-embeddings`

Recommended usage from n8n:

- After `personal-memory-capture.json` updates a durable memory file, upload that file and call `update-embeddings`.
- After `daily-world-context-refresh.json` updates `daily_world_context.md`, upload that file and call `update-embeddings`.
- After `weekly-memory-consolidation.json` rewrites the curated memory files, upload the changed files and call `update-embeddings` once at the end.
- Leave `runtime_context.md` out of automatic embedding refresh unless you explicitly enable it.

## Model changes

- Default chat model: `qwen2.5:14b-instruct-q4_K_M`
- Default summarization model: `qwen2.5:7b-instruct-q4_K_M`
- Change models through the `OLLAMA_CHAT_MODEL` and `OLLAMA_SUMMARY_MODEL` environment variables.
- If you move to a stronger model, keep the summarizer lighter unless you need better classification quality.

## Memory capture

Use the n8n webhook from `personal-memory-capture.json`.

Example request body:

```json
{
  "token": "replace_me",
  "source": "manual",
  "note": "Remember that I want the assistant to prefer local-only tools unless I explicitly approve a cloud option."
}
```

Behavior:

- raw note is stored in `inbox/raw/`
- Ollama summarizes and classifies it
- processed output is stored in `inbox/processed/`
- the chosen curated file under `memory/` is updated
- n8n should then upload the changed file to AnythingLLM and refresh workspace embeddings

## Retrieval refresh

- The new preferred method is API-driven refresh from n8n after durable file changes.
- Keep `archive/` and `inbox/` out of the main retrieval scope.
- If retrieval gets noisy, trim `recent_context_summary.md` and re-run the weekly consolidation workflow.
- Treat `runtime_context.md` carefully because re-embedding it too often creates unnecessary churn.
- Manual workspace sync is still a valid fallback if the API route fails.

## Troubleshooting stale or noisy results

- If the assistant guesses the date, confirm `runtime_context.md` is being refreshed and decide whether it should remain outside vector sync.
- If world knowledge feels stale, check the `daily_world_context.md` timestamp and confirm the corresponding upload and embedding refresh ran.
- If personal memory becomes repetitive, run the weekly consolidation workflow manually and then refresh embeddings.
- If too much irrelevant context is retrieved, reduce file size in `recent_context_summary.md` and tighten workspace scope.
- If AnythingLLM API sync fails from Docker, verify `ANYTHINGLLM_API_BASE` is reachable from the n8n container, usually via `http://host.docker.internal:3001` on Docker Desktop for Windows.
- If you later need a shared vector service across multiple apps, that is the point where `Qdrant` becomes worth reconsidering.

## Backup

Back up these folders together:

- `local-ai-data/assistant-memory/`
- the AnythingLLM desktop app data directory, including its local LanceDB workspace data
- your compose files and `.env`
- `n8n_storage` and `n8n/binary-data` if you want workflow history and execution state preserved

## Security notes

- Keep services off the public internet unless protected by VPN or a reverse proxy with authentication.
- Rotate `MEMORY_CAPTURE_TOKEN` and app secrets if they are exposed.
- Protect the AnythingLLM API key because it can upload documents and trigger embedding refreshes.
- Keep cloud integrations disabled unless intentionally enabled.