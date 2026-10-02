# Decision records

One file per significant technical choice: `NNNN-short-title.md`. Never edit an accepted
decision; write a new one that supersedes it.

Template:

```markdown
# NNNN. Title

- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD

## Context
What problem, what constraints.

## Options
Each option, with honest pros/cons.

## Decision
What we picked.

## Consequences
What gets easier, what gets harder, when to revisit.
```

| # | Decision | Status |
|---|---|---|
| [0001](0001-tech-stack.md) | Tech stack: FastAPI + Pydantic AI + plain JS (for now) | proposed |
