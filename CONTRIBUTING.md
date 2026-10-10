# Contributing

1. Read [GOAL.md](GOAL.md); features outside it will be politely declined.
2. `python -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q`
3. Keep zero runtime dependencies and Python 3.9 compatibility.
4. Add tests (use the fake GitHub client in `tests/`), run `ruff check src tests --select F,E9`.
5. Open a PR with a short description of the "why" (fittingly).
