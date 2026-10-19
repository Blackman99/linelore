---
title: "git blame 只告诉你是谁改的，linelore 告诉你为什么"
description: linelore 如何从 git blame 出发，顺着 commit → PR → 关闭的 issue → 该行附近的 review 评论把"为什么"找回来：用到的 GitHub API、离线模式、JSON 输出、局限与路线图，附真实运行输出。
---

# git blame 只告诉你是谁改的，linelore 告诉你为什么

*2026 年 10 月 · [English](git-blame-says-who-not-why.md) · 文中输出来自 linelore 0.1.1。0.1.0 不会标注远处的 review 评论，`--offline` 的提示文字也不同。*

在读 [psf/requests](https://github.com/psf/requests) 的 `src/requests/adapters.py`，第 420 行是一段关于 `verify` 参数的 docstring。这行为什么写成这样？先问 `git blame`：

```console
$ git blame -L 420,420 src/requests/adapters.py
a62a2d35d (Ian Stapleton Cordasco 2024-05-22 06:51:48 -0500 420)         * If ``verify`` is a string, (i.e., it is a user-specified trust bundle)
```

blame 给出的是"谁"和"什么时候"。commit message "Allow for overriding of specific pool key params" 讲的是"改了什么"。真正的"为什么"在别处：合并这个 commit 的 PR 描述里，这个 PR 修掉的 bug 报告里，还有有人问"为什么不那样做？"的 review 讨论里。在 GitHub 上，每查一行就要多开三四个页面，大多数编辑器插件也只做到 commit 为止。

[linelore](https://github.com/Blackman99/linelore) 就是为了补上这一段。"怎么找回老代码背后的决策原因"一直有人在问（[Ask HN](https://news.ycombinator.com/item?id=46726249)、[HN](https://news.ycombinator.com/item?id=47368874)）。其实很多时候原因写下来过，只是藏在 blame 再往后一跳的地方。

## 同一行，再往后走一步

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

来龙去脉一下就清楚了：2.32.2 让"通过 Transport Adapter 传入自定义 `SSLContext`"的用法挂了（#6715），起因是 #6655，#6716 把这个用法修了回来。上面每一行都是查出来的，不是猜出来的，linelore 不自己编摘要。

再看一行，这次原因在 code review 里：

```console
$ linelore src/requests/adapters.py:75
src/requests/adapters.py:75  from .models import PreparedRequest
  commit  c0813a2d91  2024-03-03  Ian Stapleton Cordasco
          Use TLS settings in selecting connection pool
  PR #6655  Use TLS settings in selecting connection pool  (@sigmavirus24, merged 2024-03-11)
          https://github.com/psf/requests/pull/6655
          “Previously, if someone made a request with `verify=False` then made a request where they expected verification to be enabled to the same host, they would potentially reuse a connection where TLS had not been verified. This fixes that issue.”
  review  @nateprewitt (line 66): Not against this, but I think this is the first time we're introducing typing into Requests. I'm curious if we want to start that or push it into typeshed since this will be precedent for future inline typing?
  review  @sigmavirus24 (line 66): This is for a private method (that I fully anticipate people abusing) but we're not advertising things are typed and so it's not something I'm concerned with.
```

单看一句 `import PreparedRequest` 像是无关紧要，看了 review 才知道：它是为一个类型注解引入的，也是 requests 第一次在代码里写类型注解，两位维护者当时还讨论了要不要开这个先例。

![linelore 在 psf/requests 上运行](../assets/demo.gif)

## 这条链是怎么拼出来的

linelore 约 350 行 Python，只用标准库，每一跳是一个明确的步骤。

### 1. 行 → commit（本地 git）

```text
git blame --porcelain -w -L 420,420 [--ignore-revs-file .git-blame-ignore-revs] [REV] -- src/requests/adapters.py
```

`--porcelain` 输出机器可读的头信息：commit sha、该行在那个 commit 版本里的行号（`orig_line`）、作者、时间、摘要，以及该 commit 时的文件名。`-w` 忽略纯空白改动。仓库里有 `.git-blame-ignore-revs` 时会自动带上，大规模格式化的 commit 就不会挡住真正的作者。`--rev v2.31.0` 可以按某个 tag 时的文件来 blame。

owner/repo 从 `origin` 的远程地址解析（SSH 和 HTTPS 都支持），也可以用 `--remote`、`--repo` 指定。

### 2. commit → PR（REST）

```text
GET /repos/{owner}/{repo}/commits/{sha}/pulls
```

这个接口返回与该 commit 关联的 PR。GitHub 在合并 PR 时会记录这种关联，所以 squash 合并、rebase 合并后的 commit 也能查到。linelore 最多取 3 个 PR，读取标题、作者、合并时间和描述。查不到 PR 时，多半是直接 push 到分支的，linelore 会如实提示，不去猜。

### 3. PR → 它关闭的 issue（GraphQL）

```graphql
query($o:String!,$r:String!,$n:Int!) {
  repository(owner:$o, name:$r) {
    pullRequest(number:$n) {
      closingIssuesReferences(first:10) { nodes { number title url state body } }
    }
  }
}
```

`closingIssuesReferences` 是 GitHub 自己记录的"这个 PR 关闭了哪个 issue"，PR 描述里写 `Closes #N` 和在侧边栏手动关联的都算。REST 没有对应接口，所以只有这一步走 GraphQL。另外，linelore 会扫描 PR 描述里其余的 `#N` 和 `owner/repo#N`，列为 **mentions**。前因往往藏在这里：第一个例子里的 #6655，正是引入 bug 的那次改动。

### 4. PR → 该行附近的 review 评论（REST）

```text
GET /repos/{owner}/{repo}/pulls/{number}/comments?per_page=100
```

这是行内 review 评论。linelore 只保留同一文件的评论，按与被 blame 行的距离排序。比较用的是 `orig_line`，也就是该行在那个 commit 版本里的位置，那正是 reviewer 当时看到的坐标。第二个例子里，这一行现在是第 75 行，在 commit 里是第 66 行，评论也落在第 66 行。6 行以内的评论算"附近"。附近一条都没有时，linelore 仍会给出同文件里最近的评论，但会标注 `elsewhere in this file`，免得把讲别的函数的评论当成这一行的解释。

### 开销

一个 commit 对应一个 PR 时，共 3 次 API 调用（`commits/{sha}/pulls`、`graphql`、`pulls/{n}/comments`）。带 token 在我的机器上跑上面两个例子，各约 1 秒。认证依次读取 `LINELORE_TOKEN`、`GH_TOKEN`、`GITHUB_TOKEN`，GitHub CLI 已登录时也会用 `gh auth token`。

完全没有 token 时，公开仓库照样能用，只是少了 GraphQL 这一步（GraphQL 必须认证），被关闭的 issue 会以普通 mention 的形式出现：

```console
$ linelore src/requests/adapters.py:420     # 无 token、无 gh
...
  PR #6716  Allow for overriding of specific pool key params  (@sigmavirus24, merged 2024-05-24)
          https://github.com/psf/requests/pull/6716
          “This re-enables the use case of providing a custom SSLContext via a Transport Adapter as broken in #6655 and reported in #6715 Closes #6715”
  mentions  psf/requests#6655, psf/requests#6715
```

## 离线模式

`--offline` 不联网，只显示链条的本地部分。在飞机上、在没有 API 权限的私有镜像上，或者只想看 commit 时可以用：

```console
$ linelore src/requests/adapters.py:80 --offline
src/requests/adapters.py:80  DEFAULT_POOLSIZE = 10
  commit  88d4143018  2012-12-15  Kenneth Reitz
          base adapter
  note    offline: showing local commit only
```

同一行联网查，会得到 `note  no pull request found for this commit (pushed directly?)`。这行代码写于 2012 年，那时 requests 的提交还不走 PR。

## 给编辑器和脚本用的 JSON

`--json` 包含终端视图的全部内容，外加原始字段：完整 sha、`orig_line`、作者邮箱和时区、issue 正文、review 评论链接，以及每条 review 评论的 `near` 标记。节选：

```json
{
  "repo": "psf/requests",
  "blame": {
    "sha": "c0813a2d910ea6b4f8438b91d315b8d181302356",
    "line": 75,
    "orig_line": 66,
    "summary": "Use TLS settings in selecting connection pool"
  },
  "pulls": [
    {
      "number": 6655,
      "issues": [],
      "mentions": [],
      "review_comments": [
        { "author": "nateprewitt", "line": 66, "near": true },
        { "author": "sigmavirus24", "line": 66, "near": true }
      ]
    }
  ],
  "notes": []
}
```

有了它，就能把 linelore 绑到编辑器快捷键或脚本上：

```console
$ linelore src/requests/adapters.py:420 --json | jq -r '.pulls[] | "\(.url)", (.issues[] | "  fixes \(.url)")'
https://github.com/psf/requests/pull/6716
  fixes https://github.com/psf/requests/issues/6715
```

JSON 结构目前还没冻结，v1.0 时会稳定下来。

## 局限

在真实仓库上试用后，坦白说有这些局限：

- **行范围。** `file:10-30` 会 blame 一段、按 commit 去重，并用 `-C -M` 跟随移动/重命名。v0.2 已加入。
- **移动和重命名。** blame 使用 `-C -M`，lore 会跟随重命名和拷贝（v0.2）。
- **大 PR 被 squash 合并。** PR 能找对，但描述里可能写了二十件事，你关心的那行只是其中之一。
- **`closingIssuesReferences` 不一定有数据。** 比如 `requests/adapters.py:258 --rev v2.31.0`，对应 2017 年的 PR #4371，描述里写了 "Resolves #4369"，GitHub 却没返回关闭关系。linelore 仍会把 #4369 列在 mentions 里。
- **review 评论按行距匹配。** 这是启发式的。force-push 之后的评论坐标可能对不上，过时（outdated）的评论没有行号。这些评论会标为 `elsewhere in this file`，不会直接丢掉。每个 PR 只读前 100 条 review 评论。
- **代码托管平台。** 本文以 GitHub 为例。从 v0.3 起也支持 GitLab（合并请求、`closes_issues`、diff 评论）和 Gitea/Forgejo（包括 Codeberg），详见 [Forges](../forges.md)。在 gitlab.com 上读取评审评论需要设置 `GITLAB_TOKEN`。
- **没写下来的原因，它找不回来。** PR 描述为空、也没人 review 的话，linelore 也会如实告诉你。

## 路线图

- **v0.2（已完成）**：行范围、跟踪移动/重命名、按 sha 缓存 API 响应。
- **v0.3（已完成）**：GitLab 与 Gitea/Forgejo 后端；`--open` 直接在浏览器打开 PR。
- **v0.4**：基于 `--json` 的编辑器片段（Neovim、VS Code task、Helix、Emacs）；可选的 `--summarize`，把收集到的事实交给你自己指定的 LLM 命令，并明确标注是生成内容。
- **v1.0**：稳定的 JSON 结构，发布到 PyPI 和 Homebrew。

## 试一下

```bash
pipx install git+https://github.com/Blackman99/linelore
cd 任意-github-仓库
linelore path/to/file.py:42
```

欢迎到 [Blackman99/linelore](https://github.com/Blackman99/linelore/issues) 提 issue 和想法。最有价值的反馈是：真实代码里 linelore 找错了 PR，或者漏掉了关键讨论的那一行。
