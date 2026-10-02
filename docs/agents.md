# AI coding agents

How AI coding tools are set up to work on this repo.

## Instruction files

| File | Read by | Contains |
|---|---|---|
| `AGENTS.md` | Codex, Cursor, Copilot, Gemini CLI, most agents | Commands, where code goes, hard rules. **Shared source of truth.** |
| `CLAUDE.md` | Claude Code | `@AGENTS.md` (import) + Claude-only notes |
| `.claude/agents/*.md` | Claude Code | Project subagents (below) |

Best practice followed here:
- Keep `AGENTS.md` short (under ~60 lines) and concrete: exact commands first, then rules.
  Agents read it every session; long files get skimmed.
- One source of truth: `CLAUDE.md` imports `AGENTS.md` instead of copying it.
- Details live in `docs/`; `AGENTS.md` points to them.
- Update `AGENTS.md` whenever an agent makes the same mistake twice.

## Project subagents (`.claude/agents/`)

Each has one job, the fewest tools it needs, and is checked into git so everyone gets the same set.

| Agent | Use when | Tools | Edits code? |
|---|---|---|---|
| `code-reviewer` | Before pushing / opening a PR | Read, Grep, Glob, Bash | No |
| `test-runner` | After any code change | Read, Grep, Glob, Bash | No |
| `ingest-specialist` | Adding or fixing a form source (Apps Script, scanned PDF, ...) | All | Yes |

Guidelines:
- Delegate when only the **result** matters (review verdict, test report). Keep work in the
  main session when it needs back-and-forth with you.
- Don't run more than ~3 subagents in parallel unless their work is fully independent.

## Ideas to add later

| Agent | Why |
|---|---|
| `prompt-tuner` | Runs extraction prompts against saved example messages and reports accuracy. Needs an eval set first. |
| `docs-keeper` | After a feature PR, checks `docs/` and `AGENTS.md` still match the code. |
| `security-reviewer` | Focused on the privacy rules (answers never persisted/logged) and on submit safety. |

## Sources

- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code best practices: https://code.claude.com/docs/en/best-practices
- AGENTS.md guidance: https://www.morphllm.com/agents-md-guide,
  https://marmelab.com/blog/2026/01/21/agent-experience.html
