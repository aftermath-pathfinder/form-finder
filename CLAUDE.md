@AGENTS.md

## Claude Code specifics

- Project subagents live in `.claude/agents/` (see `docs/agents.md` for when to use each).
- After changing code, run the `test-runner` agent; before pushing, run `code-reviewer`.
- When adding a new form source, delegate to `ingest-specialist`.
