# Setup rules — install, config, env vars

## 2. Setup rules

**Never run these — they need a TTY and render a broken QR code here:**

- `lark-cli config init` (bare/interactive)
- `lark-cli config init --new`
- any interactive `lark-cli config bind` with no flags

**Local workspace — use the setup script (device flow, no TTY):**

```bash
SETUP=$(find ~/.workbuddy/skills ./.workbuddy/skills -name lark_setup.py 2>/dev/null | head -1)

python3 "$SETUP"                  # feishu, opens browser
python3 "$SETUP" --brand lark     # Lark international
python3 "$SETUP" --no-browser  # print URL instead of opening
python3 "$SETUP" --force          # re-register even if already configured
```

The script is idempotent: if `appId` already exists it exits 0 immediately and does **not** re-authorize.

**Preferred agent pattern — split flow.** Never show a URL and then block polling in the same turn; in harnesses that hide intermediate output the user never sees the link.

```bash
# Turn 1 — get the URL, then END THE TURN and wait for the user
python3 "$SETUP" --print-url-only
# -> {"verification_url": "...", "device_code": "...", "resume_command": "..."}

# Turn 2 — after the user says they authorized, YOU run this (not the user)
python3 "$SETUP" --device-code <device_code>
```

Optionally render a QR code alongside the URL. `--output` only accepts a **relative** path:

```bash
lark-cli auth qrcode "<verification_url>" --output lark-qr.png   # PNG (preferred)
lark-cli auth qrcode "<verification_url>" --ascii                #ASCII, only if asked
```

Treat the URL as an opaque string — no re-encoding, no reassembling query params.

**Agent workspace (OpenClaw / Hermes / Lark Channel).** When `OPENCLAW_HOME`, `HERMES_HOME`, or `LARK_CHANNEL` is set, `config init` refuses by design — the host already provisioned an app. Bind instead, and **confirm the identity preset with the user first**:

```bash
lark-cli config bind --identity bot-only      # safer: no impersonation
lark-cli config bind --identity user-default  # needed for personal calendar/mail/drive
```

To change identity policy on the *same* app, use `lark-cli config strict-mode` — no re-bind needed.

**Manual path**, if you already hold credentials:

```bash
echo "<APP_SECRET>" | lark-cli config init --app-id <APP_ID> --app-secret-stdin --brand feishu
```

Multiple apps are supported as named profiles: `lark-cli profile list | add | use <name> | rename | remove`
(`use -` toggles back). Per-command override: `--profile <name>`.

Config lives at `~/.lark-cli/config.json` (override with `LARKSUITE_CLI_CONFIG_DIR`); agent workspaces nest under `~/.lark-cli/openclaw/` or `~/.lark-cli/hermes/`. Secrets go to the OS keychain, not the JSON.
