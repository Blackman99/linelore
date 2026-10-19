# linelore

`git blame` tells you **who** changed a line. linelore tells you **why**: it follows the commit to the pull request (or merge request) that merged it, the issues that PR closed, and the review comments left near that line. It works on GitHub, GitLab and Gitea/Forgejo, and reads which one from your remote.

![demo](assets/demo.gif)

```console
$ linelore src/requests/adapters.py:420
src/requests/adapters.py:420  * If ``verify`` is a string, (i.e., it is a user-specified trust bundle)
  commit  a62a2d35d9  2024-05-22  Ian Stapleton Cordasco
          Allow for overriding of specific pool key params
  PR #6716  Allow for overriding of specific pool key params  (@sigmavirus24, merged 2024-05-24)
          https://github.com/psf/requests/pull/6716
          “This re-enables the use case of providing a custom SSLContext via a Transport Adapter as broken in #6655 and reported in #6715 Closes #6715”
  fixes #6715  SSLV3_ALERT_HANDSHAKE_FAILURE after upgrade from 2.31.0 to 2.32.2 [closed]
          https://github.com/psf/requests/issues/6715
  mentions  psf/requests#6655
```

- Editor-agnostic: one CLI, plus `--json` for editor plugins and scripts.
- Zero dependencies (Python 3.9+ stdlib). Uses your `gh` login if you have one.
- **GitHub, GitLab, Gitea/Forgejo** (Codeberg too), hosted or self-hosted. See [Forges](forges.md).
- `--open` opens the PR or MR in your browser.
- Ranges (`file:10-30`), follows renames (`-C -M`), caches API responses. Respects `.git-blame-ignore-revs`.

Next: [Install](install.md) · [Usage](usage.md) · [Forges](forges.md) · [FAQ](faq.md)
