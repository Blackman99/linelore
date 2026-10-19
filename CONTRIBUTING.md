# Contributing

1. Read [GOAL.md](GOAL.md); features outside it will be politely declined.
2. `python -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q`
3. Keep zero runtime dependencies and Python 3.9 compatibility.
4. Add tests (use the fake forge clients in `tests/`; GitLab and Gitea tests replay trimmed real API responses from `tests/fixtures/`), run `ruff check src tests --select F,E9`.
5. A new forge backend subclasses `Forge` in `src/linelore/forge.py` and returns the same three shapes (`commit_pulls`, `closing_issues`, `pull_review_comments`); see the docstring there.
6. Open a PR with a short description of the "why" (fittingly).
