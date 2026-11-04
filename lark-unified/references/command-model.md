# Command model — flags, JSON contract, exit codes

## 4. Command model

Three tiers, in order of preference:

```bash
# Tier 1— shortcuts (prefer these): smart defaults, table output, --dry-run
lark-cli im +messages-send --chat-id oc_xxx --text "Hello"

# Tier 2 — generated API commands, 1:1 with OpenAPI endpoints
lark-cli calendar calendars list
lark-cli calendar events instance_view --params '{"calendar_id":"primary","start_time":"1700000000","end_time":"1700086400"}'

# Tier 3 — raw API, covers 2500+ endpoints
lark-cli api GET /open-apis/calendar/v4/calendars
lark-cli api POST /open-apis/im/v1/messages --params '{"receive_id_type":"chat_id"}' --data '{...}'
```

Inspect before calling a raw endpoint:

```bash
lark-cli schema                        # list everything
lark-cli schema im.chats.create        # one method (dotted form)
lark-cli schema im chats create        # same thing, space-separated
lark-cli <domain> --help               # per-domain command list
```

A `schema` result has five top-level keys: `name`, `description`, `inputSchema`, `outputSchema`, `_meta`.
Two things matter in practice:

- The **identity constraint is appended to `description`**, not a separate field — e.g.
  `创建群。Identity: bot only (tenant_access_token)`.
- **`_meta` holds what you need before calling**: `scopes`, `access_tokens`, `risk`
  (`read` / `write` / `high-risk-write`), a separate `danger` boolean, and `doc_url`.

`lark-cli <domain> --help` is the primary command list but **not guaranteed complete** — a few shortcuts are
registered hidden yet remain callable (e.g. `vc +notes`). If a name from these references is missing from
`--help`, try `lark-cli <domain> <shortcut> --help` before concluding it does not exist.

For the full mechanics of tiers 2 and 3 — typed-command discovery, `schema` output shape, `api` usage,
the complete flag table, and envelope/exit-code handling — see
[references/api_reference.md](references/api_reference.md).

### Flags that actually exist

Output format is a **single `--format` flag**. `--table`, `--csv`, `--yaml`, `--raw` do **not** exist — the old
skill listed all four and every one of them fails.

```bash
--format json     # default; --json is shorthand for this
--format table
--format ndjson   # for piping
--format csv
--format pretty   # shortcuts only -- NOT accepted by `lark-cli api`
```

Pagination: `--page-all`, `--page-limit N`, `--page-delay MS` (default 200ms). `--page-limit` defaults to 10,
but its valid range differs by tier — on shortcuts it must be **1-1000** (`--page-limit 0` is a validation
error), while on `lark-cli api` **0 means unlimited**. Individual commands also accept `--page-size` and
`--page-token`.

Other flags on a typical shortcut: `--as`, `--dry-run`, `--jq`, `--json`, `--yes` (confirm high-risk writes),
`--output`, `--params` / `--data` (JSON payloads), `--profile`.

Quiet JSON for scripts:

```bash
LARKSUITE_CLI_NO_UPDATE_NOTIFIER=1 LARKSUITE_CLI_NO_SKILLS_NOTIFIER=1 lark-cli auth status --json
```

### JSON contract — check `ok`, never `code`

Success → stdout, exit 0:

```json
{ "ok": true, "identity": "user", "data": { ... }, "meta": { "count": 1 } }
```

Error → stderr, non-zero exit:

```json
{ "ok": false, "identity": "user", "error": { "type": "authorization", "subtype": "missing_scope", "code": 99991679, "message": "...", "hint": "...", "missing_scopes": ["..."] } }
```

Test `ok == true` or the exit code. There is **no top-level `code` on success** — `code` only exists inside the error envelope and holds the upstream OpenAPI number. Judging by the legacy `{"code":0}` shape marks every success as a failure, which is dangerous around writes: a misread on `task +create` can bypass idempotency and duplicate records.

### Exit code 10 — approval gate

High-risk writes without `--yes` exit **10** with `error.type: "confirmation"`. This is not a failure. Show the
user the pending action, get explicit confirmation, then re-run with `--yes`. Never silently append `--yes`
and retry on your own.

**Identity is checked before the confirmation gate.** A high-risk command with the wrong identity exits **2**
(`resolved identity "bot" ... only supports: user`) and never reaches the gate — so exit 2 does *not* mean the
command is safe. Fix identity first, then expect 10:

```bash
lark-cli apps +openapi-key-delete --app-id <id> --key-id <k>             # exit 2  (identity)
lark-cli apps +openapi-key-delete --app-id <id> --key-id <k> --as user   # exit 10 (needs --yes)
```

### Hard rules

- **Relative paths only.** `--file`, `--output`, `--output-dir`, `@file` reject absolute paths, e.g.
  `unsafe output path: --output must be a relative path within the current directory`. Some of these flags
  accept `-` to read an out-of-tree file from stdin; pipe large payloads that way.
- Never print `appSecret` or access tokens.
- Confirm intent before writes and deletes; preview with `--dry-run`.
- Ignore `_notice.update` in output unless the user asked about versions. Update with `lark-cli update` (refreshes CLI *and* skills).
