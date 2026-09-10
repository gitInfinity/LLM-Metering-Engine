# copilot-instructions.md

For full architectural and design guidance, see the README.md.

## key files:
- src/db/database.py
- src/models.py
- src/db/db_models.py

As you create or modify files, keep the **Key Files** section above up to date.

Add a file when it contains important logic or configuration needed to understand the application's architecture, behavior, or major data flows.

Typical examples include API, database/data-layer, core service, integration, or major frontend logic, but use judgment rather than treating these examples as an exhaustive list.

Do not add trivial, generated, or low-impact files.

Update the section when a key file is added, removed, renamed, or its responsibility changes significantly.

## 1. No Assumptions
Never invent requirements, APIs, functions, schemas, env vars, or config. If it can be found in the repo, inspect it instead of guessing. Ask only when it can't be determined and materially affects the work.

## 2. Simple Code, Minimal Diff
Use the simplest implementation that solves the problem. Change only what the task requires — no unrelated cleanup, refactors, or "while I'm here" fixes. Small task = small diff.

## 3. No Overengineering
No new abstractions, wrapper classes, service layers, frameworks, or config systems unless the current task actually needs them. No caching/optimization without a measured reason.

## 4. Match Existing Style
Follow the project's existing formatter, naming, folder structure, and error-handling/logging patterns. Don't introduce new conventions or reformat unrelated code.

## 5. No Unrequested File Creation or Deletion
Don't create or delete files (docs, scripts, configs, tests, etc.) unless the task requires it or it was explicitly asked for. Never run destructive git operations unless explicitly requested.

## 6. Verify Before Claiming Success
Don't claim something works without checking (tests, build, run, request). Never fabricate output. State clearly if something couldn't be verified.

## 7. Update README on Structural Change
Whenever files/folders are added, removed, or moved, update the project README to reflect the new structure.

## 8. Installing dependancies
Make sure all libraries and dependancies are installed. Especially when you add a new dependancy or shifting to a new technology.

## 9. Project guidelines
- Use `uv` for dependency management and project commands. Prefer `uv run <command>` for Python tools and scripts.

## 10. Business Logic Regression Rules

When modifying business logic, inspect `engineering-lessons.md`
for relevant previously observed failures and their regression checks.

If a business-logic mistake is discovered, record the observed failure,
cause if known, correction, and a repeatable regression check there.

Do not log tooling, environment, formatting, or documentation issues.
