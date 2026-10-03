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
   - **Google Form link**: public forms; forms that need sign-in with the browser add-on (below).
   - **Google Apps Script web app** (`script.google.com/macros/...`): needs the browser add-on.
   - **Web form link**: any page with a normal HTML `<form>`.
   - **PDF**: must be a *fillable* PDF.
   - **Word (.docx)**: mark each blank with double braces, e.g. `Name: {{Full name}}`,
     `Date: {{Date of leave}}`.
2. **Describe your request** in the chat. Anything you mention up front (dates, names) is filled
   in automatically and not asked again.
3. **Answer the batch** of questions in one message, numbered or free-form. Say "skip" for blanks.
4. **Review**, edit anything, then **Approve**. Nothing is submitted until you approve.
   For Google Forms you can instead click **Open prefilled in my browser**: the form opens in
   your own browser with the answers filled in and you press Submit there. Handy for forms that
   need your Google sign-in.

Your answers are kept in memory only for the current request and are gone after submitting
(or after an hour). Only blank form templates are saved, under `data/`.

## Browser add-on (optional)

Google Apps Script web apps and Google Forms that require sign-in are read and submitted in a
real browser (Playwright + Chromium). Everything else works without it.

```bash
pip install playwright        # or: pip install -r requirements-browser.txt
playwright install chromium
```

Restart the app. For sign-in forms (and Apps Script apps that need your account), click
**Sign in to Google** in the left panel: a browser window opens, sign in, then close it. Your login
is kept in `data/browser-profile/` (delete that folder to sign out). This only works when Form
Finder runs on your own computer, since the window opens there. Your form answers are never saved
in that profile.

## Hosting it (Docker)

The `Dockerfile` includes the browser add-on. Set a password whenever others can reach the app:

```bash
docker build -t form-finder .
docker run -p 8000:8000 -v form-finder-data:/data \
  -e LLM_API_KEY=nvapi-... -e APP_PASSWORD=pick-a-password form-finder
```

- `APP_PASSWORD`: every page asks for it (browser login prompt, any username).
  Leave it unset only when running on your own computer.
- The `/data` volume keeps your knowledge base across restarts. Without it, forms are lost
  whenever the container restarts (common on free hosting tiers).
- "Sign in to Google" is turned off when hosted (it would open a window on the server). Use
  **Open prefilled in my browser** for sign-in forms instead.
- Works on any Docker host (Render, Railway, Fly.io, Hugging Face Spaces): point it at this repo
  and set the environment variables in its dashboard.

## Switching AI provider

AI calls use [Pydantic AI](https://pydantic.dev/docs/ai/), configured in one place (`app/llm.py`).
Any OpenAI-compatible API works by editing `.env` only:

| Provider | `LLM_BASE_URL` |
|---|---|
| NVIDIA build (default) | `https://integrate.api.nvidia.com/v1` |
| OpenAI | `https://api.openai.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Ollama (local) | `http://localhost:11434/v1` |

Other providers Pydantic AI supports (Anthropic, Gemini, Mistral, ...): set `LLM_PROVIDER` to its
name (e.g. `anthropic`), `LLM_MODEL` to the model, its usual key variable (e.g. `ANTHROPIC_API_KEY`),
and `pip install "pydantic-ai-slim[anthropic]"`.

If the provider answers with a 400 error about `response_format`, set `LLM_JSON_MODE=false`.

Backup when the free tier is busy: `LLM_FALLBACK_MODELS=openai:gpt-5.2` (comma-separated, tried in order).

## Project layout

```
app/
  main.py            API routes + serves the web page
  ai.py              every AI prompt, as Pydantic AI agents with typed outputs
  interview.py       4–6 question batching, answer validation, in-memory sessions
  ingest/            read forms: google_form, html_form, apps_script_form, pdf_form, docx_form
  fill.py            write answers into PDF / DOCX
  submit.py          submit Google Forms / HTML forms / Apps Script
  browser.py         optional real browser (Playwright) + saved Google login
  llm.py             builds the AI model from .env (provider switch + fallback)
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
