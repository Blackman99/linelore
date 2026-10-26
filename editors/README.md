# Editor integrations

Each one runs the `linelore` CLI on the line (or lines) under your cursor. Install the CLI first; set-up, keys and options are on the [Editors](https://blackman99.github.io/linelore/docs/editors/) docs page.

| Folder | Editor | Key | Shows | Reads |
|---|---|---|---|---|
| [`nvim/`](nvim/) | Neovim 0.9+ | `:Linelore`, or your `keymap` | a float at the cursor | `--json` |
| [`emacs/`](emacs/) | Emacs 27.1+ | `M-x linelore` | a `*linelore*` window | `--json` |
| [`vscode/`](vscode/) | VS Code | `Ctrl+Alt+L` (with `keybindings.json`) | a terminal panel | text |
| [`helix/`](helix/) | Helix 25.07+ | `space l l` | a popup | text |

## Tests

`tests/test_editors.py` checks each one against a scratch repo:

- **Neovim** (`nvim --headless`) and **Emacs** (`emacs --batch`, ERT in `emacs/test/`) render linelore's JSON for ten cases (GitHub, GitLab and Codeberg lookups from recorded forge answers, a range, offline lines, an uncommitted line, a summary and a failed summary) and must show the expected text and links. The Emacs test also checks that wrapped text lines up under its label.
- **Helix**: `hx` must load `helix/config.toml` without complaint, and the bindings may only use expansions Helix 25.07 has.
- **VS Code**: `tasks.json` and `keybindings.json` must parse, use only variables VS Code defines, and every binding must name a real task.
- The JSON fields the plugins read are pinned, so renaming one fails there first.

Locally, a missing editor is skipped. In CI (`LINELORE_EDITORS_REQUIRED=1`) it fails instead, so a broken install step can't pass as green.
