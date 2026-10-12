<p align="center"><img src="assets/logo-512.png" width="120" alt="linelore logo"></p>

<h1 align="center">linelore</h1>
<p align="center"><b>git blame tells you who. linelore tells you why.</b></p>
<p align="center"><a href="https://blackman99.github.io/linelore/">Home</a> · <a href="https://blackman99.github.io/linelore/docs/">Docs</a> · <a href="https://github.com/Blackman99/linelore/actions/workflows/ci.yml"><img src="https://github.com/Blackman99/linelore/actions/workflows/ci.yml/badge.svg" alt="CI"></a></p>

## The problem

`git blame` gives you a commit and a one-line message. The real reason for a line usually lives somewhere else: the pull request description, the issue it fixed, the review thread where someone asked "why not X?". Getting there is five clicks per line, and it only works inside one editor plugin. People keep asking how to find the "why" behind old code ([Ask HN](https://news.ycombinator.com/item?id=46726249), [HN](https://news.ycombinator.com/item?id=47368874)).

linelore does the chain in one command: **line → commit → PR → closing issues → nearby review comments.**

![demo](site/demo.gif)

## Install

```bash
pipx install git+https://github.com/Blackman99/linelore
```

Python 3.9+, no dependencies. Uses `GH_TOKEN` / your `gh` login if present; works anonymously on public repos.

## Usage

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

`file:10-30` for a range (commits deduped), `--json` for editors/scripts, `--offline` for local only, `--rev` to blame at a tag. Full docs: <https://blackman99.github.io/linelore/docs/>

## License

MIT
