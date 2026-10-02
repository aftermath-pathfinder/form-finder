# AGENTS.md

Instructions for any AI coding agent (Claude Code, Codex, Cursor, ...) working in this repo.
Humans: start with `README.md`, then `docs/`.

## What this is

A web app: the user describes a request in plain words, the AI picks the matching form from a
knowledge base, asks 4–6 questions per message, shows a review screen, then submits the online
form or returns a filled PDF/DOCX. See `docs/architecture.md`.

## Commands

```bash
pip install -r requirements.txt               # install
uvicorn app.main:create_app --factory --reload  # run on http://localhost:8000
python -m pytest                              # tests (offline, no API key needed)
ruff check app tests && ruff format app tests # lint + format; must pass before commit
```

## Where things go

| Change | File |
|---|---|
| Any prompt sent to the AI | `app/ai.py` only |
| New form source (reader) | `app/ingest/<source>_form.py` + register in `app/ingest/__init__.py` |
| Filling a file / submitting online | `app/fill.py` / `app/submit.py` |
| Question batching, answer validation | `app/interview.py` |
| AI provider / model setup | `app/llm.py` (usually just `.env`) |
| HTTP routes | `app/main.py` only |
| UI | `app/static/` (plain HTML/JS, no build step) |

## Hard rules

- **Never persist or log the user's answers.** They live in `Session` (memory) and are dropped
  after submit. Only blank templates go to `data/`.
- **Never submit without the review step.** `POST /api/chat/{id}/submit` is the user's approval.
- **Tests never hit the network or a real AI.** Use `fake_model()` from `tests/helpers.py`
  (a Pydantic AI `FunctionModel`).
- Messages in `IngestError` / `SubmitError` / `HTTPException` are shown to the user: plain
  English, say what to do next.
- Every new ingester ships with a parse test and a fill-or-submit-payload test.
- Escape all user/form text in the UI with `esc()` before inserting HTML.

Full standards: `docs/coding-standards.md`. Tech decisions and why: `docs/decisions/`.

## Git

- Small commits, imperative subject ≤ 72 chars ("Add Apps Script ingester").
- `python -m pytest` and `ruff check` green before every push.
