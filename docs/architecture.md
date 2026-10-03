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
          or (Google Forms) "Open prefilled" → submit.google_prefill_url → you submit it yourself
```

The session (with your answers) is dropped as soon as one of these delivery paths completes.
With `APP_PASSWORD` set, `auth.PasswordMiddleware` guards every route.

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
| `browser.py` | optional Playwright browser: saved Google login, throwaway contexts, frame finding | parse forms, see answers outside a submit |
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
| Apps Script web app * | browser: frame with the most inputs → `parse_html_form(scripted=True)` | browser: fill each field, click Submit |
| Sign-in-only Google Form * | browser with saved Google login → `parse_google_form` | POST to `/formResponse` via the browser's request API (login cookies) |

\* Needs the optional browser add-on (`app/browser.py`, Playwright + Chromium). Without it these
links fail with a message saying how to install it.

### Browser add-on

- **Saved login:** `POST /api/browser/login` opens a visible Chromium on Google's sign-in page using
  the profile `<data_dir>/browser-profile`. Only works when the app runs on your own computer
  (loopback request, a screen available). That profile holds only the Google login.
- **Throwaway contexts:** reading and submitting copy the login cookies out of the profile into a
  fresh headless context, so nothing typed into a form (autofill, history, cache) touches disk.
- **Apps Script:** the user's HTML sits two iframes deep (outer page → sandbox → `userHtmlFrame`) and
  usually submits via `google.script.run`. Fields may have only an `id`, so `parse_html_form`
  records how to find each one in `submit["selectors"]` (and `submit["option_selectors"]` per
  radio/checkbox option); submit uses those to fill the same frame.
