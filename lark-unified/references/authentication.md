# Authentication — OAuth, scopes, identity, re-auth

## 3. Authentication

```bash
lark-cli auth status --json --verify        # who am I, is the token valid
lark-cli whoami                             # effective identity, short form
lark-cli auth check --scope "<scope>"       # exit 0 = present, 1 = missing
lark-cli auth scopes                        # scopes this app already holds
lark-cli auth list                          # all authenticated users
lark-cli auth login --device-code <code>    # finish a split-flow login
lark-cli auth logout --json                 # clears LOCAL session only
```

`auth login` **requires** a scope selector (`--domain`, `--scope`, or `--recommend`). Scopes accumulate across logins, so you can start with three and add more later — nothing already granted is lost.

Read `identity`, `verified`, `identities.user.status`, `identities.user.userName`, `identities.user.tokenStatus` from `auth status`.

### Request the fewest scopes that do the job

Every scope on the consent screen is one more thing the user has to approve, and in many tenants an
unapproved scope lands in an admin review queue (`待发布` in the console). `--domain base` asks for
**40** base scopes — create, update, delete, roles, workflows, advanced permissions — when reading one
table needs **three**. That turns a five-second read into an approval ticket.

So the default is `--scope`, naming exactly what the command needs:

```bash
# Read records from a Base -- this is the entire scope set
lark-cli auth login --scope "base:record:read base:table:read base:field:read" --no-wait --json
```

One `--scope` string, space- or comma-separated. A misspelled scope is rejected server-side with
`error.type: "authentication"`, so typos fail loudly instead of silently granting nothing.

**Find the scopes before asking for anything:**

1. Each domain reference has a `## Permissions` table mapping shortcut → exact scopes. For example
   [lark-base.md](references/lark-base.md) lists `+record-list` as `base:record:read`.
2. For native API commands, `lark-cli schema <service>.<resource>.<method>` returns `_meta.scopes`.
   This does **not** cover base — `schema base.*` fails with `Unknown service: base`, since the base
   shortcuts are not in the schema registry. Use the reference table there.
3. If a call still fails, the error carries `missing_scopes`. Request exactly those and nothing else.

**Widening, in increasing order of cost:**

```bash
# 1. Precise -- the default, and what the official lark-shared skill recommends
lark-cli auth login --scope "base:record:read base:table:read base:field:read" --no-wait --json

# 2. A whole domain minus the destructive parts
lark-cli auth login --domain base \
  --exclude "base:record:delete,base:table:delete,base:field:delete,base:role:delete" \
  --no-wait --json
```

`--exclude` subtracts from `--domain`; both combine additively with `--scope`.

**`--recommend` is not a minimal option — it is one of the broadest.** The official README describes it
as "recommended auto-approval scopes", which reads like a small safe subset. It is not. The CLI's embedded
scope catalogue marks **310** scopes as `recommend: true`, spanning `im` (51), `base` (43), `directory`
(33), `docs` (31), plus `approval`, `calendar`, `contact`, `minutes` and more — including **13 delete
scopes** (`base:record:delete`, `base:role:delete`, `base:workflow:delete`, `im:chat:delete`,
`space:document:delete`, …). It therefore requests *more* than `--domain base`, not less. Reasonable for a
long-lived personal setup where the user knowingly authorizes broadly; wrong for "read one table".

**`--domain all` is a last resort, never a starting point.** It requests scopes across all 23 domains —
mail, calendar, attendance, approval, contact — for a task that touches one. Use it only when the user
explicitly asks to authorize everything up front, and never as a reaction to a `missing_scope` error.

### Minimum scopes for common tasks

| Task | Scopes to request |
|---|---|
| Read Base records / tables | `base:record:read base:table:read base:field:read` |
| Read a Base including view config | add `base:view:read` |
| Write Base records | add `base:record:create base:record:update` |
| Read a docx | `docx:document:readonly` |
| Create a docx | `docx:document:create` |
| Read a spreadsheet range | `sheets:spreadsheet:read` |
| Write spreadsheet cells | `sheets:spreadsheet:write_only` |
| Today's calendar | `calendar:calendar.event:read` |
| Create a calendar event | `calendar:calendar.event:create calendar:calendar.event:update` |
| Read chat messages | `im:message:readonly im:chat:read` |
| Send a message as the user | `im:message.send_as_user im:message` |
| Read mail | `mail:user_mailbox.message:readonly` + address / subject / body read scopes |
| List or read wiki nodes | `wiki:node:retrieve` |
| Read my tasks | `task:task:read` |
| Look up a colleague | `contact:user:search` — **user identity only**, `--as bot` is rejected with exit 2 |
| Search docs by keyword | `search:docs:read` |
| Download a Drive file | `drive:file:download drive:drive.metadata:readonly` |

Resolving a Base or doc from a **wiki** URL additionally needs `wiki:node:read` / `wiki:node:retrieve`.
Downloading a Base attachment additionally needs `docs:document.media:download`.

### Check before re-authorizing

`auth check` says whether the token already covers a scope, so you avoid a redundant consent screen.
It exits **1** when something is missing and prints `{"ok":false,"missing":[...]}`; an
`{"error":"not_logged_in"}` body means there is no user session at all. **Capture the exit code on the
same line** — piping into `head` or `jq` overwrites `$?` with the pipeline's status:

```bash
OUT=$(lark-cli auth check --scope "base:record:read base:table:read base:field:read" --json); RC=$?
# RC=0 -> already granted, just run the command
# RC=1 -> read OUT.missing and request only those
```

`auth scopes` shows what the app currently holds under `userScopes`; a freshly registered app holds
only `offline_access`.

### Where this differs from the official README

The official README's Quick Start opens with `lark-cli auth login --recommend`, and the official
`lark-shared` skill puts "获取全部权限 → `--domain all`" at the top of its auth lookup table. Both are
optimized for one-time broad setup, not for a single task.

The least-privilege guidance above is **not** a departure from official intent — `lark-shared` states it
directly:

> `lark-cli auth login --scope "<missing_scope>"   # 按具体 scope 授权（推荐，符合最小权限原则）`

and the upstream design follows the same principle: each shortcut declares "the narrowest scope the
upstream API accepts", and `internal/auth/scope.go` `MissingScopes` does **exact-string** matching, so a
broader scope form does not satisfy a narrower requirement. Declaring or requesting wide does not help.

What this skill changes is only the **default ordering**: `--scope` first, `--domain` when a task genuinely
spans a domain, `--recommend` / `--domain all` only on explicit user request.

### Identity: bot vs user

| Identity | Flag | Token | Reach |
|---|---|---|---|
| Bot | `--as bot` | `tenant_access_token` | App-level. Only needs console scopes — **no `auth login`**. Cannot see the user's calendar, mail, or drive. |
| User | `--as user` | `user_access_token` | The user's own resources. Needs console scopes **and** `auth login`. |

`--as` accepts `user`, `bot`, `auto`. Resolution is `--as` flag → `config default-as` → `auto`. Because it is not hard-wired to bot, **pass `--as` explicitly** whenever identity matters.

The classic failure: `--as bot` returns an empty agenda because the bot is reading *its own* empty calendar. Personal resources need `--as user`.

### Missing permissions

Errors carry `missing_scopes`, `console_url`, and `hint`.

- **Bot** → pass `console_url` to the user verbatim so they enable the scope in the developer console. **Never** run `auth login` for a bot.
- **User** → request **exactly** the scopes in `missing_scopes`, nothing more:

  ```bash
  lark-cli auth login --scope "<scope_1> <scope_2>" --no-wait --json
  ```

  Do not respond to a missing scope by widening to `--domain <name>` or `--domain all`. Scopes accumulate,
  so a second precise login later costs the user one more consent tap — while an over-broad first request
  can cost them an admin approval cycle.

`auth logout` only clears the local session. Revoking server-side authorization, or a single granted scope, must be done by the user in Lark's authorization-management page.
