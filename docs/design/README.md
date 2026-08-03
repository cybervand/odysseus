# Design documents

Decision records for this fork's changes. Each doc captures **why** a thing
is the way it is: the observed problem, the evidence, the decision, what was
rejected, and what's still open. Commit messages say what changed; these say
why — read them before re-litigating or extending an area.

## Rules

- One doc per subsystem/feature, numbered, kebab-case: `NNN-short-name.md`.
- Start from [000-template.md](000-template.md).
- **Update the existing doc when a round of work touches its area** — append
  to its Decision log rather than writing a new doc. New doc only for a new
  subsystem.
- Keep evidence concrete: run counts, log lines, commit hashes. "It seemed
  better" is not a rationale.
- Open items live in the doc that owns them, not in a global backlog.

## Index

| Doc | Area | Status |
|---|---|---|
| [001](001-harmony-tool-aliasing.md) | gpt-oss harmony tool-name aliasing | Shipped; upstream PR #5878 |
| [002](002-completion-verifier.md) | Agent completion verifier | Shipped; evolving |
| [003](003-document-library-awareness.md) | Document library awareness (manifest + tools) | Shipped |
| [004](004-edit-document-targeting.md) | edit_document targeting + edit UX redesign | Partially shipped; open items |
| [005](005-document-diff-pipeline.md) | Document diff pipeline (chip, editor review, verifier) | Shipped |
| [006](006-workspace-binding.md) | Workspace selection and confinement | Upstream design documented; extension proposed |
| [007](007-deployment-runbook.md) | copperwarehouse deployment runbook | Living document |
