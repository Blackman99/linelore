# Editors

Ask "why is this line like this?" without leaving the file. Four ready-made integrations live in [`editors/`](https://github.com/Blackman99/linelore/tree/main/editors). All of them run the `linelore` CLI, so install that first and check `linelore demo` works.

| Editor | What you get | Ranges | Reads |
|---|---|---|---|
| [Neovim](#neovim) 0.9+ | a float next to the cursor, links open with `⏎` | visual selection | `--json` |
| [Emacs](#emacs) 27.1+ | a `*linelore*` buffer, links are buttons | active region | `--json` |
| [VS Code](#vs-code) | a task; output in the terminal panel, links are Ctrl/Cmd+click | typed in (`10-30`) | text |
| [Helix](#helix) 25.07+ | a popup | the selection | text |

Neovim and Emacs parse `linelore --json` and lay it out themselves. VS Code tasks and Helix's `:sh` can only show text, so they run plain `linelore`; its output already puts every URL on its own line, which both terminals make clickable.

## Neovim

With [lazy.nvim](https://github.com/folke/lazy.nvim):

```lua
{
  "Blackman99/linelore",
  config = function(plugin)
    vim.opt.rtp:append(plugin.dir .. "/editors/nvim")
    require("linelore").setup({ keymap = "<leader>gl" })
  end,
}
```

Without a plugin manager, add `editors/nvim` from a clone to `runtimepath`.

`<leader>gl` (or `:Linelore`) on a line; select lines and press it again (or `:'<,'>Linelore`) for a range. The float opens next to the cursor with focus inside it:

```text
┌ linelore ─────────────────────────────────────────────────────────────┐
│ src/requests/utils.py:795                                             │
│ value_changed = value is not None                                     │
│                                                                       │
│ commit    1d7fd6c8b3 · 2017-06-06 · mlcrazy                           │
│           Fixes error swallowing in set_environ                       │
│ PR #4134  Raise exceptions in utils.set_environ                       │
│           @mlcrazy · merged 2017-06-09                                │
│           https://github.com/psf/requests/pull/4134                   │
│           “fixes #4127”                                               │
│ fixes     #4127 UnboundLocalError: local variable 'bypass' referenced │
│           before assignment [closed]                                  │
│           https://github.com/psf/requests/issues/4127                 │
│ review    @Lukasa (line 615): We don't need this newline.             │
│ review    @Lukasa (line 617): `None` is implicit in `get`, you can    │
│           leave it out.                                               │
│ review    @nateprewitt (line 621): @Lukasa what are your thoughts on  │
│           adding `value_changed = value is not None`, and using that  │
│           single value for both conditionals? The fact these two      │
│           checks are bound is implicit and has the potential to get   │
│           out of sync as soon as one change…                          │
│ review    @Lukasa (line 621): Works for me!                           │
└ ⏎ open link · o open PR · y copy · q close ───────────────────────────┘
```

| Key | In the float |
|---|---|
| `⏎` or `gx` | open the link on (or just below) the cursor |
| `o` | open the pull request |
| `y` | copy the link to the clipboard |
| `q`, `Esc` | close; leaving the float closes it too |

The lookup runs in the background (`vim.system`, or `jobstart` on 0.9), so the editor never freezes while the forge answers. If the buffer has unsaved changes, the float says so: line numbers come from the file on disk.

Options, with their defaults:

```lua
require("linelore").setup({
  cmd = "linelore",   -- or { "uvx", "linelore" }
  args = {},          -- e.g. { "--offline" } or { "--rev", "v1.2" }
  summarize = false,  -- add --summarize (see Summaries); shown in its own section
  border = "single",
  max_width = 96,
  keymap = nil,       -- e.g. "<leader>gl", set for normal and visual mode
})
```

Highlight groups link to standard ones and can be overridden: `LineloreTitle`, `LineloreCode`, `LineloreLabel`, `LineloreSha`, `LineloreUrl`, `LineloreMuted`, `LineloreNote`, `LineloreSummary`, `LineloreError`.

## Emacs

```elisp
(use-package linelore
  :load-path "~/src/linelore/editors/emacs"
  :commands linelore
  :bind ("C-c g l" . linelore))
```

Or with Emacs 29's `package-vc-install`:

```elisp
(package-vc-install '(linelore :url "https://github.com/Blackman99/linelore" :lisp-dir "editors/emacs"))
```

`M-x linelore` on a line, or with the region active for a range. The answer opens in `*linelore*` below the current window:

| Key | In `*linelore*` |
|---|---|
| `RET`, click | open the link at point |
| `TAB`, `S-TAB` | next, previous link |
| `o` | open the pull request |
| `w` | copy the link at point |
| `g` | look up the same lines again |
| `q` | quit |

Customize with `M-x customize-group RET linelore`: `linelore-command` (a list, e.g. `("uvx" "linelore")`), `linelore-extra-arguments`, `linelore-summarize`. `C-u M-x linelore` asks for a summary once. Faces: `linelore-title`, `linelore-code`, `linelore-label`, `linelore-sha`, `linelore-muted`, `linelore-summary`.

## VS Code

Copy [`editors/vscode/tasks.json`](https://github.com/Blackman99/linelore/blob/main/editors/vscode/tasks.json) to `.vscode/tasks.json` (or merge its `tasks` and `inputs`), then run **Tasks: Run Task → linelore: this line**. Three tasks are included:

- **linelore: this line** for the cursor's line;
- **linelore: a range of lines…** asks for `START-END`, because VS Code has no task variable for a selection's first and last line;
- **linelore: open the pull request** runs `linelore --open`.

Output goes to a dedicated terminal panel; Ctrl/Cmd+click a URL to open it. For keys, add [`editors/vscode/keybindings.json`](https://github.com/Blackman99/linelore/blob/main/editors/vscode/keybindings.json) to yours: `Ctrl+Alt+L` explains the line, `Ctrl+Alt+Shift+L` opens the PR.

## Helix

Helix 25.07 added command expansions (`%{buffer_name}`, `%{selection_line_start}`, …), which is all this needs. Merge [`editors/helix/config.toml`](https://github.com/Blackman99/linelore/blob/main/editors/helix/config.toml) into `~/.config/helix/config.toml`:

```toml
[keys.normal.space.l]
l = ":sh linelore --no-color %{buffer_name}:%{selection_line_start}-%{selection_line_end}"
o = ":sh linelore --open %{buffer_name}:%{cursor_line}"
```

`space l l` explains the line, or every line of a multi-line selection (`x` a few times first). `space l o` opens the pull request. The answer appears in a popup.

## Summaries in editors

With `summarize = true` (Neovim), `linelore-summarize` (Emacs) or `--summarize` added to a task's or binding's arguments, linelore asks your own model command for a summary (see [Summaries](summaries.md)). Neovim and Emacs show it below the facts under its label, `Summary (generated by llm, may be wrong; not checked by linelore)`, or `No summary: …` with the reason if the command failed. The facts above it are always the same as without it.

## Build your own

Anything that can run a command and read JSON can do this. The fields the bundled plugins read are pinned by [`tests/test_editors.py`](https://github.com/Blackman99/linelore/blob/main/tests/test_editors.py), so renaming one fails a test before it can break an editor:

- top level: `forge` (`github`, `gitlab`, `gitea`), `path`, `notes[]`; a single line has `blame` and `pulls[]`, a range has `range{start,end}` and `commits[]` (each with `blame`, `lines[]`, `pulls[]`, `notes[]`).
- `blame`: `sha`, `line`, `author`, `author_time` (Unix seconds), `summary`, `content`, `uncommitted` (true for lines you haven't committed).
- each pull/merge request: `number`, `title`, `url`, `author`, `merged_at` (ISO 8601 or null), `state`, `body` (an excerpt), `issues[]` (`number`, `title`, `url`, `state`, `promoted`), `mentions[]` (strings like `owner/repo#12`), `review_comments[]` (`author`, `line`, `body`, `near`: false when no comment was close to the line and these are from elsewhere in the file).
- `model_summary` (only with `--summarize`): `by`, `text` (null on failure), `error`, `disclaimer`.

Run it from the file's directory with an absolute path, as `FILE:LINE` or `FILE:START-END`. Exit codes 0, 3 (the forge lookup failed; local facts and a note are still printed) and 4 (the summary failed) all come with JSON on stdout; 1 and 2 mean an error on stderr and no JSON.
