# 0001. Tech stack

- Status: **accepted** (Pydantic AI migration done 2026-10-02)
- Date: 2026-10-02

## Context

The scaffold is FastAPI + a hand-rolled AI client + plain JS. Questions raised:
is that "too vanilla", and what should it be built on long term?

Constraints:
- Must read/fill PDFs and DOCX, and later drive a real browser (Apps Script, Google sign-in).
  Python has the best libraries for all three (pypdf, python-docx, Playwright).
- AI provider must be switchable; starting with NVIDIA's free GLM endpoint, which is
  OpenAI-compatible (`https://integrate.api.nvidia.com/v1`).
- AI output must be **structured** (field id → value) and **validated**.
- One developer, learning as they go: fewer moving parts wins.

## Decisions by layer

### Backend web framework: **keep FastAPI**

| Option | Verdict |
|---|---|
| **FastAPI** (current) | ✅ Async (AI + HTTP calls), Pydantic built in, file uploads, free API docs at `/docs`. |
| Django | ❌ Admin/ORM/auth we don't need yet; heavier to learn. Revisit if we add user accounts + DB. |
| Flask | ❌ Sync-first, no built-in validation. Strictly less than FastAPI here. |
| Node / Next.js full-stack | ❌ Loses Python's PDF/DOCX/Playwright ecosystem. |

### AI layer: **Pydantic AI** (accepted, migrated)

| Option | Verdict |
|---|---|
| Hand-rolled (previous `app/llm/`) | Works, ~80 lines. But we maintain JSON parsing, retries, and every provider ourselves. |
| **Pydantic AI** | ✅ Typed outputs: the model's reply is validated into a Pydantic model and **auto-retried** on bad output (replaces `parse_json`/`complete_json`). 20+ providers plus any OpenAI-compatible URL via `OpenAIProvider(base_url=...)`. `FallbackModel` can switch to a backup provider when the free tier is down. Ships test models, replacing our `FakeLLM`. Same team as Pydantic/FastAPI, so the style matches. |
| LiteLLM | Good provider switch (100+ providers) but only that. No validation or retries. Could sit *under* Pydantic AI later if needed. |
| LangChain / LangGraph | ❌ for now. LangGraph shines for multi-step, durable, branching agent workflows. Our flow is a simple loop with state already in `Session`. Revisit if the browser-driving agent becomes multi-step with checkpoints. |
| CrewAI / multi-agent frameworks | ❌ We don't have multiple cooperating agents. |

**How it was done:** `ai.py` has three `Agent`s with typed outputs (`Enrichment`, `Match`,
`Extraction`) using `PromptedOutput`. The match agent has an `output_validator` that makes the
model retry if it names a form that isn't in the catalog. `app/llm.py` builds the model from `.env`
(OpenAI-compatible URL, any Pydantic AI provider, optional `FallbackModel`). Tests use
`FunctionModel`. Checked against a local OpenAI-compatible server: GLM-style `<think>` tags and
```json fences in replies are handled.

**Still to verify with a real key:** prompted output sends `response_format: {"type": "json_object"}`.
If NVIDIA's GLM rejects that parameter, set the model profile's `supports_json_object_output` to
`False` in `app/llm.py`.

### Frontend: **keep plain HTML/JS now; React + Vite when the UI grows**

| Option | Verdict |
|---|---|
| **Plain JS** (current) | ✅ No build step, ~200 lines, easy to learn. |
| HTMX | Nice for server-rendered pages; awkward for our JSON chat + file download flow. |
| **React + Vite** | Next step when we add: multiple chats, drag-and-drop uploads, richer review screen, login. Serve the built files from FastAPI. |
| Next.js | ❌ Brings its own server; duplicates FastAPI. |

### Browser automation (next feature): **Playwright for Python**

Needed for Apps Script web apps (form lives in a sandboxed iframe) and sign-in-only Google
Forms. Playwright over Selenium: auto-waiting, iframe handling, saved login state.

### Tooling

| Tool | Use |
|---|---|
| `ruff` | lint + format (adopted) |
| `python -m pytest` | tests (adopted) |
| `uv` | faster installs + lockfile (adopt with the Pydantic AI migration) |
| `pyright` | type checking (adopt once code settles) |
| `pre-commit` | run ruff/python -m pytest before each commit (optional) |

## Consequences

- Pydantic AI removes our hand-written JSON parsing and gives validation + retries + provider
  fallback for one dependency.
- Frontend stays build-free until there's a concrete reason (listed above) to add React.
- Revisit LangGraph when the browser agent needs multi-step plans with resumable state.

## Sources

- Pydantic AI, OpenAI-compatible providers: https://pydantic.dev/docs/ai/models/openai/
- Framework comparison: https://www.speakeasy.com/blog/ai-agent-framework-comparison
- Pydantic AI vs LangGraph: https://www.zenml.io/blog/pydantic-ai-vs-langgraph
- NVIDIA NIM OpenAI-compatible endpoint: https://www.mindstudio.ai/blog/nvidia-nim-free-models-ai-workflows
