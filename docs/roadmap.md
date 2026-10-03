# Roadmap

## Now
- [ ] Verify the real NVIDIA GLM model id and a full run with a real key
- [ ] Test a live submit against a Google Form you own
- [x] Migrate `ai.py` to Pydantic AI ([ADR 0001](decisions/0001-tech-stack.md))

## Next
- [x] Playwright: Google Apps Script web apps (optional browser add-on)
- [x] Playwright: forms that require Google sign-in (sign in once; only the login is saved, never answers)
- [ ] Try the browser add-on against real Apps Script apps and a sign-in-only Google Form
- [x] Password protection (`APP_PASSWORD`) + Dockerfile
- [ ] Deploy it (Render / Railway / Hugging Face Spaces) and build the Docker image for real

## Later
- [ ] Scanned/flat PDFs (OCR + place text by position)
- [ ] Word forms without `{{ }}` markers (detect `Name: ______` blanks)
- [ ] Google Form grids and file-upload questions
- [ ] React + Vite frontend (when the triggers in ADR 0001 hit)
