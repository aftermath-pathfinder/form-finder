# Coding standards

Enforced by tools where possible (`ruff`, `python -m pytest`). The rest is checked in review.

## 1. Python

- **Python 3.11+**, type hints on every function signature.
- **Formatting and lint:** `ruff format` + `ruff check` (config in `pyproject.toml`, 120 cols).
  Don't argue with the formatter.
- **Data shapes are Pydantic models** (`app/models.py`) or dataclasses. No passing loose dicts
  between modules except the `answers: dict[str, Any]` map.
- **Async** for anything that does network I/O (`httpx.AsyncClient`, AI calls). File parsing
  stays sync.
- **Names:** modules `snake_case`, one concern per module; functions are verbs
  (`parse_pdf`, `fill_docx`, `submit_online`).
- **Comments explain why, not what.** Docstrings on public functions when the name isn't enough.
- **No new dependency** without a line in the PR saying why and what was considered.

## 2. Errors

| Situation | Raise | Becomes |
|---|---|---|
| Can't read a form | `IngestError` | HTTP 422 |
| Online submit failed | `SubmitError` | HTTP 502 |
| AI unreachable / bad reply | `LLMError` | HTTP 502, or degrade (see below) |

- Error messages are **user-facing**: say what went wrong and what to do next.
  ✅ "This PDF has no fillable fields. Try a fillable version of the form."
  ❌ "KeyError: '/AcroForm'"
- Always chain: `raise X(...) from e`.
- **Degrade, don't crash, when the AI is optional** (e.g. `enrich_form` falls back to raw labels).

## 3. AI / prompts

- **All prompts live in `app/ai.py`.** Nowhere else builds messages.
- Ask for **JSON**, then **validate in code** (`interview.normalize`). Never trust the model's
  value for a choice/date/number without checking it.
- Include "never invent values" in extraction prompts; pass today's date for relative dates.
- Provider-specific code stays in `app/llm/`. The rest of the app only calls
  `LLMProvider.complete` / `complete_json`.

## 4. Privacy (non-negotiable)

- User answers: **memory only** (`Session`), deleted after submit or 1 hour.
- Never write answers to disk, logs, or error messages. Never send them anywhere except the AI
  provider (for extraction) and the target form.
- Secrets only via `.env` (git-ignored). Never commit keys.

## 5. Tests

- `python -m pytest`, offline. **No real network, no real AI**: use `FakeLLM` and build fixtures in code
  (`tests/helpers.py` makes PDFs/DOCX on the fly).
- Every ingester: one **parse** test and one **fill or submit-payload** test.
- Bug fix → add the test that would have caught it.
- Test names say the behaviour: `test_unanswered_required_are_reasked_then_left_for_review`.

## 6. Frontend (`app/static/`)

- Plain HTML/CSS/JS, no build step (see `docs/decisions/0001-tech-stack.md` for when that changes).
- Every piece of user or form text goes through `esc()` before `innerHTML`.
- Colours via CSS variables; must work in light and dark mode and at phone width.

## 7. Git and PRs

- Branch per change. Commit subject: imperative, ≤ 72 chars ("Add Apps Script ingester").
- Before pushing: `ruff check app tests && ruff format --check app tests && python -m pytest`.
- PR description: what changed, why, how you tested it. Screenshots for UI changes.
- Update `docs/` in the same PR when behaviour or architecture changes.
