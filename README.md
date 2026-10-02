# Form Finder

Tell it what you need ("I need to file a leave for next Friday"). It finds the right form in your
knowledge base, asks you **4–6 questions at a time**, shows you a review screen, then submits the
online form for you or hands back the filled PDF/Word file.

## Run it (first time)

You need Python 3.11+.

```bash
git clone https://github.com/aftermath-pathfinder/form-finder.git
cd form-finder
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env (next section)
uvicorn app.main:create_app --factory --reload
```

Open http://localhost:8000.

### Get a free AI key (NVIDIA)

1. Go to https://build.nvidia.com/z-ai/glm-5-3 and sign in.
2. Click **Get API Key** and copy it (starts with `nvapi-`).
3. Paste it into `.env` as `LLM_API_KEY=...`.
4. In the page's code sample, check the `model=` value and put it in `LLM_MODEL` if it differs
   from `z-ai/glm-5.3`.

## Using it

1. **Add forms** in the left panel:
   - **Google Form link**: public forms only for now.
   - **Web form link**: any page with a normal HTML `<form>`.
   - **PDF**: must be a *fillable* PDF.
   - **Word (.docx)**: mark each blank with double braces, e.g. `Name: {{Full name}}`,
     `Date: {{Date of leave}}`.
2. **Describe your request** in the chat. Anything you mention up front (dates, names) is filled
   in automatically and not asked again.
3. **Answer the batch** of questions in one message, numbered or free-form. Say "skip" for blanks.
4. **Review**, edit anything, then **Approve**. Nothing is submitted until you approve.

Your answers are kept in memory only for the current request and are gone after submitting
(or after an hour). Only blank form templates are saved, under `data/`.

## Switching AI provider

All AI calls go through one small interface (`app/llm/base.py`). Any OpenAI-compatible API works
by editing `.env` only:

| Provider | `LLM_BASE_URL` |
|---|---|
| NVIDIA build (default) | `https://integrate.api.nvidia.com/v1` |
| OpenAI | `https://api.openai.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Ollama (local) | `http://localhost:11434/v1` |

For a provider with a different API, add a class in `app/llm/` that implements
`complete(messages) -> str`, register it in `app/llm/__init__.py`, and set `LLM_PROVIDER`.

## Project layout

```
app/
  main.py            API routes + serves the web page
  ai.py              every AI prompt: describe form, match request, extract answers
  interview.py       4–6 question batching, answer validation, in-memory sessions
  ingest/            read forms: google_form, html_form, pdf_form, docx_form
  fill.py            write answers into PDF / DOCX
  submit.py          submit Google Forms / HTML forms
  llm/               swappable AI providers
  static/            the web page (plain HTML/JS, no build step)
tests/               run with: python -m pytest
docs/                architecture, standards, decisions, roadmap
```

## Docs

- [docs/architecture.md](docs/architecture.md): how a request flows through the app
- [docs/coding-standards.md](docs/coding-standards.md): rules for code and reviews
- [docs/decisions/](docs/decisions/): why this stack (FastAPI, Pydantic AI proposal, frontend)
- [docs/agents.md](docs/agents.md): AI coding agent setup (`AGENTS.md`, `.claude/agents/`)
- [docs/roadmap.md](docs/roadmap.md): what's next
