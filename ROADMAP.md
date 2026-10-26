# Roadmap

- **v0.1 (done)** – FILE:LINE → commit → PR → closing issues → mentions → nearby review comments; `--json`, `--offline`, `--rev`, ignore-revs, GHES `--api`. v0.1.1: review comments far from the line are labelled, clearer `--offline` note, `--rev` works when the file has since moved.
- **v0.2 (done)** – line ranges (`file:10-30`, dedupe commits); follow through move/rename commits (`git blame -C -M`); cache API responses per sha (memory + `~/.cache/linelore`, `LINELORE_CACHE` to override/disable). Also: promote Fixes/Closes/Resolves body/title mentions when GraphQL `closingIssuesReferences` is empty.
- **v0.3 (done)** – GitLab and Gitea/Forgejo backends (auto-detected from the remote; `--forge`, `--api` for self-hosted); `--open` to launch the PR/MR in a browser. Also: Gitea merge-commit fallback, GHES GraphQL endpoint fix, per-forge tokens and cache.
- **v0.4 (done)** – editor integrations in `editors/` (Neovim float and Emacs buffer reading `--json`, VS Code tasks, Helix bindings), tested headless in CI; opt-in `--summarize` through a model command you configure, printed under its own label after the facts and kept in a separate `model_summary` JSON field.
- **v1.0** – stable JSON schema, PyPI release, Homebrew formula.
