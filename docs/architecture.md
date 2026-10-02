# Architecture

## Request flow

```
 You: "I need a leave next Friday"
          │
          ▼
 1. MATCH      ai.match_form ──── picks a form from the knowledge base
          │
          ▼
 2. PREFILL    ai.extract_answers ── pulls answers already in the request (date = next Friday)
          │
          ▼
 3. ASK        interview.Session.next_batch ── 4–6 unanswered fields
          │      ▲
          │      └── ai.extract_answers on your reply, repeat until nothing left
          ▼
 4. REVIEW     editable screen; missing required fields highlighted
          │
          ▼  (you click Approve)
 5. DELIVER    online form → submit.submit_online
               PDF / DOCX   → fill.fill_pdf / fill.fill_docx → download
```

Adding a form is separate: `ingest/` reads the source into a `FormSchema`, then
`ai.enrich_form` writes a one-line purpose (for matching) and a friendly question per field.

## Core data

- **`FormSchema`** (`app/models.py`): one form: title, kind, fields, plus `submit` details
  (action URL, hidden inputs, PDF checkbox values). Saved as JSON in `data/forms/`.
- **`FormField`**: id (what the form calls it), label, type, options, required.
- **`Session`** (`app/interview.py`): one request in progress. **Memory only**, 1-hour TTL,
  deleted after submit.

## Modules and their boundaries

| Module | Owns | Must not |
|---|---|---|
| `main.py` | HTTP routes, wiring | contain prompts or parsing |
| `ai.py` | every prompt, as Pydantic AI agents with typed outputs | do HTTP or touch files |
| `llm.py` | building the AI model from settings | know about forms |
| `ingest/` | source → `FormSchema` | call the AI |
| `interview.py` | batching, validation, sessions | call the AI or HTTP |
| `fill.py`, `submit.py` | output | ask questions |
| `knowledge_base.py` | storing templates + schemas | store answers |

## Batching rule (4–6 questions)

`batch_size(n)`: if n ≤ 6 ask all, else split into even batches of 4–6
(7 → 4+3, 13 → 5+4+4). Your reply is matched against **all** open fields, so answering
ahead is fine. Unanswered required fields are re-asked once, then left for the review screen.
Unanswered optional fields are asked once.

## Supported sources

| Source | Read | Deliver |
|---|---|---|
| Google Form (public) | page data `FB_PUBLIC_LOAD_DATA_` | POST to `/formResponse` |
| HTML form | BeautifulSoup | GET/POST with fresh hidden inputs |
| Fillable PDF | pypdf AcroForm fields | filled PDF download |
| DOCX | `{{placeholder}}` markers | filled DOCX download |
| Apps Script web app | **not yet** (needs a browser) | **not yet** |
| Sign-in-only Google Form | **not yet** | **not yet** |
