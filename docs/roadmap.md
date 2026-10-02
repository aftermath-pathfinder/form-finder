# Roadmap

## Now
- [ ] Verify the real NVIDIA GLM model id and a full run with a real key
- [ ] Test a live submit against a Google Form you own
- [ ] Decide on [ADR 0001](decisions/0001-tech-stack.md); if accepted, migrate `ai.py` to Pydantic AI

## Next
- [ ] Playwright: Google Apps Script web apps
- [ ] Playwright: forms that require Google sign-in (sign in once per session, nothing saved)
- [ ] Deploy somewhere with a password (Render / Hugging Face Spaces)

## Later
- [ ] Scanned/flat PDFs (OCR + place text by position)
- [ ] Word forms without `{{ }}` markers (detect `Name: ______` blanks)
- [ ] Google Form grids and file-upload questions
- [ ] React + Vite frontend (when the triggers in ADR 0001 hit)
