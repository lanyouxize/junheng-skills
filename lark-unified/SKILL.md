---
name: lark-unified
description: 飞书与 Lark 的统一 CLI 套件：覆盖消息、文档、表格、多维表格、日历、邮件、任务、知识库、会议、OKR、审批等模块。当用户要通过命令行操作飞书任一能力时用。
description_zh: "飞书/Lark 全能套件：消息、文档、表格、多维表格、日历、邮件、任务、Wiki、幻灯片、会议、OKR、审批等 18 个业务域；飞书项目（Meegle）工作项按需转子技能"
description_en: "Lark/Feishu unified CLI: messaging, docs, sheets, base, calendar, mail, tasks, wiki, slides & more; routes Feishu Project (Meegle) to an on-demand sub-skill"
version: "2.3.0"
allowed-tools: Bash, Read
display_name: "lark-unified"
display_name_en: "lark-unified"
visibility: "public"
metadata:
  requires:
    bins: ["lark-cli"]
  optionalBins: ["meegle"]
  cliHelp: "lark-cli --help"
  alignedWith: "larksuite/cli v1.0.82; larksuite/meegle-cli v1.0.19"
---

# Lark Unified

Wraps the official **`lark-cli`** (github.com/larksuite/cli, MIT) — 200+ commands over 18 Lark/Feishu business domains. This skill adds a non-TTY setup path and condenses the official 26-skill layout into one entry point.

It also routes to **飞书项目 / Meegle** (a separate product with a separate CLI) through an on-demand sub-skill. Read section 0 first to pick the right product.

## 0. Product routing — decide this before anything else

"Lark/Feishu" covers **two products that share nothing at runtime**: separate binaries, separate
authentication, separate credential stores. Picking the wrong one wastes an auth round-trip and, worse,
produces a confident answer about the wrong system.

| | Lark 协作 (this skill) | 飞书项目 / Meegle (sub-skill) |
|---|---|---|
| Binary | `lark-cli` | `meegle` |
| Install | required, always present | **on demand only** — see section 0.2 |
| Auth | `lark-cli auth login`, OAuth scopes | `meegle auth login`, device-code, no scope model |
| Credentials | `~/.lark-cli/`, OS keychain | `~/.meegle/`, OS keychain — **not shared** |
| Entry point | sections 1-8 below | [skills/meegle/SKILL.md](skills/meegle/SKILL.md) |

### 0.1 Routing signals

Route on **signal words first**, and only then on the command surface.

**→ Feishu Project / Meegle (load the sub-skill):** 飞书项目 · Meegle · Meego · 工作项· 需求单·
缺陷 · Bug 单 · 迭代 · 排期 · 工时 · 节点流转 · 状态流转 · MQL · 空间 (project space) ·
`project_key` · 计划表 / WBS · 度量图表 · 资源库 · 交付物 · a `project.feishu.cn` or `meegle.com` URL.

**→ Lark collaboration (stay here):** 消息 / 群 · 文档 / docx · 表格 / sheet · 多维表格 / Base ·
日历 · 邮件 · Wiki · 云盘 / Drive · 妙记 · 会议 · OKR · 审批 · 打卡 · 通讯录.

### 0.2 Word collisions — read this, do not guess

Several everyday words map to **both** products with completely different meanings. Getting these wrong
is the single most likely routing failure.

| Word | Lark collaboration |飞书项目 / Meegle | How to tell |
|---|---|---|---|
| **任务 / task** | Lark Task — a personal to-do item (`lark-cli task +create`) | a work-item **type** (`task`) inside a project space, alongside 需求 / 缺陷 | Mentions a 空间 / 项目 / 迭代 / work-item ID → Meegle. A standalone personal reminder → Lark Task. |
| **待办 / todo** | `lark-cli task +get-my-tasks` | `meegle mywork todo` | "我的飞书待办" → Lark Task. "飞书项目里我的待办" / mentions 空间 → Meegle. |
| **项目 / project** | usually loose wording for "a piece of work" | a **space** (`project_key`), a first-class entity | "项目空间" / "哪个项目下" → Meegle. |
| **评论 / comment** | doc, sheet and Drive comments | comments on a work item | Target is a doc/file → Lark. Target is a work item → Meegle. |
| **视图 / view** | Base view (`lark-cli base +view-list`) | Meegle view (`meegle view get`) | Mentions Base / 多维表格 / `app_token` → Lark. Mentions 空间 / 工作项 → Meegle. |
| **状态 / 流转** | n/a | node flow / state flow transitions | Any流转 wording → Meegle. |
| **排期 / 工时** | calendar events | `workhour list-schedule`, node schedules | 排期 of people or work items → Meegle. A meeting on a calendar → Lark. |

**When the signal is genuinely ambiguous, ask.** One clarifying question costs far less than authorizing
the wrong product. Do not "try both".

> This table and the domain table in section 5 are exhaustive for **Lark collaboration only**. If a
> request does not fit any Lark domain in section 5, do not force the closest-looking match — re-check
> section 0.1 and consider that it belongs to the Meegle sub-skill.

### 0.3 Loading the Meegle sub-skill

The `meegle` binary is **not** part of the default setup and must not be installed pre-emptively. Install
it only when the user has clearly asked for Feishu Project work.

```bash
# 1. Preflight -- installed? authenticated? one call, JSON + exit code
STATUS=$(find ~/.workbuddy/skills ./.workbuddy/skills -name meegle_status.py 2>/dev/null | head -1)
python3 "$STATUS"; echo "exit=$?"
```

| Exit | State | What to do |
|---|---|---|
| 0 | ready | Read the sub-skill and proceed |
| 3 | not installed | Install (step 2 below), then re-check |
| 4 | installed, not logged in | Run the device-code flow in the sub-skill's `auth-guard.md` |
| 5 | unparseable | Inspect `meegle auth status --format json` by hand |

Why a script rather than probing with a business command: Meegle registers its business commands **only
after login**, so an unauthenticated CLI answers `unknown command "workitem" for "meegle"` — byte-for-byte
identical to a genuinely nonexistent command. Only `auth status` distinguishes the two.

```bash
# 2. Install the binary ONLY -- both flags matter
npx -y @lark-project/meegle@latest install --no-skills --no-auth --host <host> --lang zh
```

- `--no-skills` — **required.** Without it the official wizard runs `skills add` and installs its own
  copy of the meegle skill into the agent's global skill directory, producing a duplicate that competes
  with the sub-skill bundled here.
- `--no-auth` — keeps installation and login separate, so the login step can follow the split
  device-code flow instead of blocking on a browser.
- **Requires Node.js 18+** (for `npx`). If `node --version` fails or reports < 18, stop and tell the
  user to install Node first — do not attempt a workaround.
- The wizard runs `npm install -g @lark-project/meegle`. **Tell the user before running it** and get
  their agreement: it writes to the global npm prefix, which is a change outside this workspace.
- `<host>` is `project.feishu.cn` (飞书项目) or `meegle.com` (Meegle international). If the user has not
  said which, ask — a wrong host means authorizing against the wrong tenant.

```bash
# 3. Hand off. Read the sub-skill before issuing any meegle business command.
```

Then read [skills/meegle/SKILL.md](skills/meegle/SKILL.md) and follow it. Login uses the CLI's **split
device-code flow**, wrapped by `scripts/meegle_setup.py`:

```bash
SETUP=$(find ~/.workbuddy/skills ./.workbuddy/skills -name meegle_setup.py 2>/dev/null | head -1)
python3 "$SETUP" --host <host> --print-url-only                  # turn 1: show URL, then END THE TURN
python3 "$SETUP" --resume --device-code <dc> --client-id <cid># turn 2: exchange for a token
```

Exit codes on `--resume`: **0** authenticated · **2** pending, poll again · **4** device code expired or
denied. Bare `meegle auth login` needs a TTY and fails here with `INTERACTIVE_BROWSER_REQUIRED`. The
sub-skill's auth section is adapted for this environment — see
[skills/meegle/NOTICE.md](skills/meegle/NOTICE.md) for exactly what was changed relative to upstream.

**Never mix the two CLIs in one pipeline.** IDs are not portable: a Meegle `work_item_id` means nothing
to `lark-cli`, and a Lark `open_id` is not a Meegle `user_key`. To cross products, resolve the identity
explicitly on each side (`lark-cli contact +search-user` ↔ `meegle user search`).

## 1. Preflight — run this first, every time

> Section 0 comes first. This preflight covers **`lark-cli` only** — it says nothing about whether the
> `meegle` binary exists or is authorized. For a Feishu Project request, run the Meegle check in
> [section 0.3](#03-loading-the-meegle-sub-skill) instead.

Do **not** guess whether Lark is configured. Run the status script; it prints JSON and sets an exit code.

```bash
# Works whether the skill is installed user-level or project-level
STATUS=$(find ~/.workbuddy/skills ./.workbuddy/skills -name lark_status.py 2>/dev/null | head -1)
python3 "$STATUS" --json; echo "exit=$?"
```

| Exit | State | What to do |
|---|---|---|
| 0 | configured | Proceed. If `userLoggedIn:false`, only `--as bot` work is possible. |
| 3 | not installed | `npx -y @larksuite/cli@latest install` (takes several minutes) |
| 4 | not configured | Local workspace → run `lark_setup.py`. Agent workspace → `lark-cli config bind` |
| 5 | unparseable | Inspect `lark-cli config show` manually |

For a fuller picture — version, config file, bot/user identity, endpoint reachability — run the CLI's own
health check. It always exits 0, so read the `ok` field and per-check `status` (`pass` / `warn` / `fail`):

```bash
lark-cli doctor
```

> **Why a script and not a grep?** `lark-cli config show` emits **`appId`** (camelCase). Matching on `app_id` never succeeds, which silently reports "not configured" and re-triggers authorization on every run. The script parses JSON and accepts both spellings. Never reintroduce a `grep "app_id"` check.

**Before you trigger any authorization prompt**, work out which scopes the task actually needs and check
whether they are already granted. Asking for a whole domain because it is convenient pushes the user into
an admin approval queue for permissions the task never uses. See
[Request the fewest scopes that do the job](#request-the-fewest-scopes-that-do-the-job).


### Need setup, auth or command details?

The three heavy sections (setup rules, authentication, command model) now live in `references/`. Read only the one your current step needs:

| Topic | Read when | File |
|-------|-----------|------|
| Setup rules | First install, config paths, env vars, `lark-cli` bootstrap | `references/setup.md` |
| Authentication | OAuth flows, scope selection, re-auth, bot vs user identity | `references/authentication.md` |
| Command model | Flag grammar, JSON output contract, exit codes, approval gate | `references/command-model.md` |
| API reference (Tier 2/3) | Looking up an endpoint not covered by the per-domain files | `references/api_reference.md` |

## 5. Domains

`lark-cli --help` lists 23 domains. The 18 you will actually reach for are below; shortcut names come from the CLI's own command registry — verify with
`lark-cli <domain> --help` before improvising.

> Domain name vs reference filename: the CLI invocation is **`lark-cli docs`** (plural), even though the
> reference file is named `lark-doc.md` after the official skill folder. Same for `vc`, `note`, `apps`.

| Domain | What it does | Representative shortcuts | Reference |
|---|---|---|---|
| **im** | Messages, group chats, search, files, reactions, cards, Feed pins | `+messages-send` `+messages-reply` `+messages-search` `+messages-mget` `+messages-resources-download` `+chat-list` `+chat-create` `+chat-search` `+chat-update` `+chat-members-list` `+chat-messages-list` `+threads-messages-list` `+flag-create` `+feed-shortcut-create` | [lark-im.md](references/lark-im.md) |
| **docs** | Docx create/read/update, media, history, search | `+create` `+fetch` `+update` `+search` `+media-insert` `+media-upload` `+media-download` `+media-preview` `+resource-download` `+resource-update` `+history-list` `+history-revert` | [lark-doc.md](references/lark-doc.md) |
| **drive** | Files, folders, permissions, comments, versions, sync | `+upload` `+download` `+inspect` `+search` `+create-folder` `+move` `+delete` `+import` `+export` `+export-download` `+preview` `+list-comments` `+add-comment` `+member-add` `+member-list` `+version-history` `+permission-get-setting` `+status` `+pull` `+push` `+sync` | [lark-drive.md](references/lark-drive.md) |
| **sheets** | Spreadsheet read/write, styles, charts, pivots, filters | `+workbook-create` `+workbook-info` `+workbook-export` `+sheet-create` `+sheet-copy` `+sheet-info` `+csv-get` `+cells-get` `+cells-set` `+cells-search` `+cells-replace` `+cells-clear` `+range-sort` `+chart-create` `+pivot-create` `+filter-create` `+csv-put` | [lark-sheets.md](references/lark-sheets.md) |
| **base** | Multi-dimensional tables: records, fields, views, dashboards, roles | `+url-resolve` `+base-create` `+base-get` `+table-list` `+record-list` `+record-search` `+record-get` `+record-batch-create` `+record-batch-update` `+record-delete` `+record-upsert` `+field-list` `+field-create` `+data-query` `+view-list` `+view-set-filter` `+dashboard-list` `+role-create` | [lark-base.md](references/lark-base.md) |
| **calendar** | Events, agenda, free/busy, meeting rooms, RSVP | `+agenda` `+create` `+update` `+get` `+search-event` `+freebusy` `+suggestion` `+room-find` `+rsvp` `+meeting` | [lark-calendar.md](references/lark-calendar.md) |
| **task** | Tasks, tasklists, subtasks, reminders, assignees | `+create` `+update` `+get-my-tasks` `+get-related-tasks` `+search` `+complete` `+reopen` `+assign` `+comment` `+reminder` `+followers` `+set-ancestor` `+tasklist-create` `+tasklist-search` `+tasklist-members` `+tasklist-task-add` `+upload-attachment` | [lark-task.md](references/lark-task.md) |
| **mail** | Read, search, send, reply, forward, drafts, templates, watch | `+messages` `+message` `+send` `+reply` `+reply-all` `+forward` `+draft-create` `+draft-edit` `+draft-send` `+message-trash` `+message-modify` `+thread` `+triage` `+watch` `+signature` `+share-to-chat` `+lint-html` | [lark-mail.md](references/lark-mail.md) |
| **wiki** | Knowledge spaces, node trees, members | `+space-list` `+space-create` `+delete-space` `+node-list` `+node-get` `+node-create` `+node-copy` `+node-delete` `+move` `+move-to-drive` `+member-add` `+member-list` `+member-remove` | [lark-wiki.md](references/lark-wiki.md) |
| **contact** | User and bot lookup | `+search-user` `+get-user` `+search-bot` | [lark-contact.md](references/lark-contact.md) |
| **slides** | Presentations, slide pages, screenshots | `+create` `+add-slide` `+delete-slide` `+replace-slide` `+replace-pages` `+xml-get` `+screenshot` `+media-upload` `+history-list` | [other-domains.md](references/other-domains.md) |
| **markdown** | Native Markdown files in Drive | `+create` `+fetch` `+patch` `+overwrite` `+diff` | [other-domains.md](references/other-domains.md) |
| **vc** | Meetings, recordings, notes, live meeting control | `+search` `+detail` `+recording` `+notes`† `+meeting-events` `+meeting-join` `+meeting-leave` `+meeting-list-active` `+meeting-message-send` | [other-domains.md](references/other-domains.md) |
| **minutes** | Minutes metadata, AI summaries, todos, media | `+search` `+detail` `+summary` `+todo` `+download` `+upload` `+update` `+speaker-replace` `+word-replace` `+apply-permission` | [other-domains.md](references/other-domains.md) |
| **okr** | Objectives, key results, cycles, progress | `+create` `+batch-create` `+patch` `+cycle-list` `+cycle-detail` `+progress-create` `+progress-list` `+progress-update` `+indicator-update` `+weight` `+reorder` `+upload-image` | [other-domains.md](references/other-domains.md) |
| **approval** | Approval tasks, instances, definitions | *No shortcuts.* `approval tasks query` `approval tasks approve` `approval instances create` `approval approvals search` `approval approvals get` | [other-domains.md](references/other-domains.md) |
| **attendance** | Personal punch records | *No shortcuts.* `lark-cli attendance --help`, `lark-cli schema attendance.<resource>.<method>` | [other-domains.md](references/other-domains.md) |
| **apps** | Miaoda/Spark app dev, hosting, DB, logs, releases | `+init` `+create` `+list` `+get` `+update` `+release-create` `+db-execute` `+db-table-list` `+env-set` `+env-list` `+file-upload` `+log-list` `+trace-list` `+html-publish` `+automation-list` `+role-list` | [other-domains.md](references/other-domains.md) |

Also available: **contact** (`+search-user` `+get-user` `+search-bot` — see [lark-contact.md](references/lark-contact.md)), **event** (WebSocket subscriptions: `event list`, `event consume <event_key>`, `event status`, `event stop`), **whiteboard** (`+update` `+export`, plus hidden `+query`†), **note** (`+detail` `+transcript`), **mindnotes** (mind-note nodes), **application** (self-management for the bound app), **approval**, **attendance**.

> † Registered as hidden: absent from `--help` but callable (`vc +notes`, `whiteboard +query`).
>
> Shortcut names are checked against the CLI's own registry — a wrong name is rejected outright. These do **not** exist despite looking plausible: `+cells-read`, `+cells-find`, `+sheet-list`, `+workbook-list`, `+workbook-get`, `+get-range`, `+range-get`. Use `+csv-get` / `+cells-get`, `+cells-search`, and `+workbook-info` (which also lists child sheets). When unsure, run `lark-cli <domain> --help`.

**This table does not contain 飞书项目 / Meegle.** Work items, node/state transitions, MQL, project
spaces, WBS plans and workhour scheduling are a different product with a different binary — go to
[section 0](#0-product-routing-decide-this-before-anything-else) and load the sub-skill. Do not
substitute `lark-cli task` or `lark-cli approval` for a Meegle request just because they are the nearest
row here.

## 6. Worked examples

```bash
# Send a message
lark-cli im +chat-search --keyword "engineering"
lark-cli im +messages-send --chat-id oc_xxx --text "Hello team" --as bot

# Preview a risky write first
lark-cli im +messages-send --chat-id oc_xxx --text "test" --dry-run

# Today's agenda (personal resource -> must be user identity)
lark-cli calendar +agenda --as user

# Create a doc from markdown
lark-cli docs +create --doc-format markdown \
  --content $'<title>Weekly Report</title>\n  # Progress\n- Shipped X'

# Inspect a workbook (this also lists child sheets), then read a range.
# Quote A1 references -- an unquoted '!' triggers bash history expansion.
lark-cli sheets +workbook-info --spreadsheet-token <token> --as user
lark-cli sheets +csv-get --spreadsheet-token <token> --range 'Sheet1!A1:D20' --as user

# Query base records with pagination
lark-cli base +record-list --app-token <app_token> --table-id tbl_xxx --page-all --page-limit 5

# All chats as a table
lark-cli im +chat-list --as user --format table
```

## 7. Entity IDs

`open_id` (ou_), `user_id`, `union_id`, `email` · chat `oc_` · message `om_` · `document_id` / `doc_token` · `file_token` / `file_key` · base `app_token` + `tbl_` · `spreadsheet_token` · wiki `space_id` + `node_token` · `calendar_id` (`primary` for self) + `event_id` · `task_guid` · `note_id`

Tokens are not interchangeable across domains. A wiki node wrapping a doc needs `wiki +node-get` to resolve the underlying `doc_token` first.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Consent screen asks for dozens of scopes / admin approval needed for a simple read | `--domain <name>` or `--domain all` used instead of `--scope` | Request the exact scopes from the domain reference's Permissions table; `--domain base` is 40 scopes, reading a table is 3 |
| Setup re-runs authorization every time | `grep "app_id"` against camelCase `appId` output | Use `lark_status.py` / `lark_setup.py`; never grep `app_id` |
| `not configured` in an agent workspace | Host app not bound | `lark-cli config bind --identity bot-only` |
| `config init` refuses | Agent workspace guard | Use `config bind`, or `--force-init` only if the user truly wants a second app |
| Empty agenda / empty drive | Bot reading its own resources | Re-run with `--as user` |
| `missing_scope` on bot | Console scope not enabled | Send `console_url` to the user; do not `auth login` |
| `unsafe file path` | Absolute path passed | Use a relative path under cwd |
| Exit code 10 | High-risk write needs confirmation | Confirm with the user, re-run with `--yes` |
| Every call "fails" in a wrapper script | Checking `code == 0` | Check `ok == true` or exit code |
| Broken QR code / hang | Interactive `config init` | Use `lark_setup.py` |
| User never sees the auth URL | URL shown and polled in one turn | Split flow: `--print-url-only`, end turn, then `--device-code` |
| `unknown command "workitem"` from `meegle` | Meegle registers business commands **only after login** — an unauthenticated CLI looks identical to a nonexistent command | Run `meegle auth status --format json`; if `authenticated:false`, log in first (see the sub-skill) |
| Asked about 工作项 / 需求 / 迭代, but `lark-cli` has no such domain | Wrong product | [Section 0](#0-product-routing-decide-this-before-anything-else) — this is Meegle, not Lark collaboration |
| A duplicate meegle skill appears after install | Official wizard ran `skills add` | Reinstall with `--no-skills`; remove the globally added copy |

Update both CLI and skills together:

```bash
lark-cli update
```
