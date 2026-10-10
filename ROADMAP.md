# Roadmap

- **v0.1 (done)** – FILE:LINE → commit → PR → closing issues → mentions → nearby review comments; `--json`, `--offline`, `--rev`, ignore-revs, GHES `--api`. v0.1.1: review comments far from the line are labelled, clearer `--offline` note, `--rev` works when the file has since moved.
- **v0.2** – line ranges (`file:10-30`, dedupe commits); follow through "move/rename" commits (`-C -M`); cache API responses per sha.
- **v0.3** – GitLab and Gitea/Forgejo backends; `--open` to launch the PR in a browser.
- **v0.4** – editor snippets (Neovim, VS Code task, Helix, Emacs) using `--json`; optional `--summarize` via a user-supplied LLM command, clearly labelled.
- **v1.0** – stable JSON schema, PyPI release, Homebrew formula.
