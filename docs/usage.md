# Usage

```bash
cd your-repo
linelore path/to/file.py:42          # the story behind line 42
git lore path/to/file.py:42          # same, as a git subcommand
linelore file.py:42 --rev v1.2.0     # blame as of a tag/commit
linelore file.py:42 --json           # for scripts and editors
linelore file.py:42 --offline        # local commit only, no network
linelore file.py:42 --repo org/name  # when origin is a fork or mirror
```

## What you get

1. **commit** – sha, date, author, summary (from `git blame -w`).
2. **PR** – the pull request(s) GitHub associates with that commit, with a description excerpt.
3. **fixes** – issues the PR closes (needs a token; GraphQL).
4. **mentions** – other `#123` / `owner/repo#123` references in the PR body.
5. **review** – review comments on that file, the ones within 6 lines of your line first.

## Editor integration

`--json` prints one object: `blame`, `pulls[]` (each with `issues`, `mentions`, `review_comments`) and `notes`. Bind it to a key in your editor, e.g. in Vim:

```vim
nnoremap <leader>w :echo system('linelore --no-color '.expand('%').':'.line('.'))<CR>
```
