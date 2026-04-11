# Contributing

Thanks for contributing to Xpdite.

## Contribution Workflow

1. Fork and clone repository.
2. Create a focused branch from latest main.
3. Implement change with tests and documentation updates.
4. Run quality checks locally.
5. Open PR with clear context and validation notes.

## Setup

```bash
git clone https://github.com/<your-user>/xpdite.git
cd xpdite
bun install
bun run install:python
```

## Quality Gates

Before opening a PR, run the Build and Validate command set documented in `docs/development.md`.

## Pull Request Requirements

- Clear title and problem statement.
- Explain why change is needed.
- Keep scope focused; avoid mixed unrelated changes.
- Include screenshots for UI changes.
- Include API or behavior contract updates where applicable.
- Update docs in `docs/` for user-visible or integration-impacting changes.

## Coding Expectations

- Follow existing architecture boundaries (API layer thin, logic in services).
- Keep type safety in both Python and TypeScript.
- Avoid broad refactors unless explicitly scoped.
- Add regression tests for bug fixes.

## Commit Message Style

Use conventional prefixes:

- `feat:`
- `fix:`
- `refactor:`
- `docs:`
- `test:`
- `chore:`

Examples:

```text
feat: add scheduled job run-now endpoint validation
fix: preserve tab context in mobile relay broadcast path
docs: align api reference with websocket message contract
```

## Areas Typically Needing Contributions

- Cross-platform robustness (non-Windows workflows)
- MCP tool integrations and reliability
- Mobile bridge adapter edge-case handling
- Performance and startup optimization
- Test coverage expansion for integration-heavy flows

## Code of Conduct and License

- Follow repository `CODE_OF_CONDUCT.md`.
- By contributing, you agree to the project license terms.
