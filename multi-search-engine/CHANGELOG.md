# Changelog

## v2.4.1 (2026-10-13)
- **Consistency pass (M9 regression + doc-sync).** No behavioural change.
  - `scripts/search_report.py` re-saved with **LF** line endings. It was the only one of the
    five scripts stored as CRLF, inconsistent with `engine_health.py`, `fetch_clean.py`,
    `validate_results.py` and `check_engine_consistency.py`.
  - Version metadata unified at `v2.4.1` across all five sources
    (`SKILL.md` / `metadata.json` / `_skillhub_meta.json` / `CHANGELOG.md` / `CHANNELLOG.md`).

## Backfill - M9 doc-sync (2026-10-13)
> The two items below **shipped without a changelog entry**. They are backfilled here by the
> M9 "regression + doc-sync" pass, sourced from the workspace report sections 10.1-10.4.
> Every script and reference named below is present in the bundle; dates come from the
> delivery records. Nothing was inferred beyond what the artifacts themselves can evidence.

- **M1 (2026-10-11, corresponds to v2.1.3)**
  - New `scripts/check_engine_consistency.py`: cross-checks the engine roster (14 checks;
    truth source = `config.json`) and version numbers (6 checks) across every document source.
    Exit codes `0` consistent / `1` inconsistent / `2` suspect truth source.
  - `references/advanced-search.md`: added a **Toutiao** chapter (section order aligned with
    `config.json`); the Toutiao engine is now listed in `SKILL.md` too.
  - Roster ruling: removed `Jisilu` (not a search engine) and added `Shenma` - the domestic
    group stays at 8 and the total stays at 17.
  - `CHANNELLOG.md` rosters aligned with `config.json` (domestic was short by one entry;
    international was missing `Google HK`).

- **M2 (2026-10-12)**
  - New `references/result-contract.md`: the machine-readable result contract `mse.result/1`
    (top level `{schema, query, language?, results[]}`; rules V1-V11).
  - New `scripts/validate_results.py`: contract validator (`--selftest` 17 cases / `--json` /
    `--summary`). `status` has four non-mergeable states: `ok` / `empty` / `blocked` / `error` -
    "engine blocked" must never masquerade as "no results".

## v2.4.0 (2026-10-13)
- **New: engine health ledger** (`scripts/engine_health.py` + `references/health-contract.md`)
  — closes roadmap item O-5 ("record per-engine success/failure/empty on every search,
  output an availability ranking"), turning "which engine is down today" from memory into data.
  - Registers every `mse.result/1` batch into `engine-health.jsonl` (one record per
    batch × engine) and emits the `mse.health.summary/1` availability board.
  - **`empty` counts as usable, `blocked`/`error` do not** — an engine being intercepted
    must never masquerade as "no results".
  - **Four verdicts, never merged**: `cross`-style third state `insufficient-data`
    (attempts < `--min-attempts`) exists so that "not enough samples" can never
    masquerade as "unhealthy". Order of checks is the semantics.
  - Dedupe key = `(batch_id, engine)`, scope = the **whole ledger** (batch content hash,
    filename-independent); commit order = write temp file → read-back verify
    (new records present AND old records intact) → `os.replace`.
  - Accepts multi-query batches (a ledger accumulates across queries by design —
    intentional difference from `search_report.py`); `--window N` / `--no-append` /
    `--prune-older-than N [--yes]` (dry-run by default; undated records always kept).
  - Reuses `validate_results.py` for V1–V11 pre-checks; does not duplicate any rule.
- `--selftest` 55 cases (incl. truth-source falsification: patch `config.json` and watch
  verdicts flip); 9 mutation rounds all turned the gate red after one fixture fix.

## v2.3.0 (2026-10-13)
- **New: cross-verification report** (`scripts/search_report.py` + `references/report-contract.md`)
  — consumes `mse.result/1` batches and emits `mse.report/1`, closing roadmap item F-1
  ("mechanically flag results that only one engine returned").
  - **Three verdicts, never merged**: `cross-verified` / `single-engine` (pending review) /
    `insufficient-engines` (no basis to cross-check). The third state exists so that
    "only one engine responded" can never masquerade as "this claim is dubious".
  - Two clustering dimensions: normalized URL (scheme/host case, `www.`, default port,
    fragment, tracking params, query order, trailing slash) **and** normalized-title similarity
    (default 0.90) — the title dimension is what recognizes the same article when Baidu returns
    a redirect link and Bing returns the canonical URL.
  - Reuses `validate_results.py` for V1–V11 pre-checks; does not duplicate any rule.
  - `--min-engines` / `--title-threshold` / `--json` / `--md -o` / multi-batch merge.
- `--selftest` 36 cases (incl. falsification cases); 5 mutation rounds all turned the gate red.

## v2.2.0 (2026-10-12)
- **New: full-text extraction layer** (`scripts/fetch_clean.py`) — URL → LLM-ready Markdown,
  closing the "we only ever get the link, never the body" gap (roadmap O-4 + F-2, the same capability).
  - Stdlib-only: minimal DOM built on `html.parser.HTMLParser`, no bs4/lxml.
  - Drops scripts/styles/nav/footers/asides/forms; scores `<article>`/`<main>` + id/class hints
    + text volume to pick the main container; converts headings/lists/code/quotes/tables/links.
  - Strips permalink anchors (`¶`, `class="headerlink"`) — they are page chrome, not prose.
  - Adapters are **data, not code** (`ADAPTERS`): `github` (repo/blob → raw README), `github-raw`,
    plus a `csdn` entry marked `verified: false` (this environment gets HTTP 521 on article pages).
  - **Honest by default**: honest UA (`mse-fetch/1.0`), robots.txt respected; `--ua browser` and
    `--ignore-robots` are explicit opt-ins. Unreachable robots is allowed but always announced in `notes`.
- **New contract `mse.fetch/1`** (`references/fetch-contract.md`): 4-state `status`
  (`ok` / `empty` / `blocked` / `error`) so "blocked by a WAF" never masquerades as "page has no content".
- Metadata version unified at 2.2.0 (`SKILL.md`, `metadata.json`, `_skillhub_meta.json`, `CHANGELOG.md`, `CHANNELLOG.md`).

## v2.1.3 (2026-10-11)
- Metadata version unified at 2.1.3 (`SKILL.md`, `_skillhub_meta.json`)
- Engine set confirmed at 17 (8 domestic + 9 global)

> Note: change details for v2.1.0–v2.1.2 were not shipped with this bundle and cannot be
> recovered from local artifacts. They are intentionally left unspecified rather than guessed.

## v2.0.1 (2026-02-06)
- Simplified documentation
- Removed gov-related content
- Optimized for ClawHub publishing

## v2.0.0 (2026-02-06)
- Added 9 international search engines
- Enhanced advanced search capabilities
- Added DuckDuckGo Bangs support
- Added WolframAlpha knowledge queries

## v1.0.0 (2026-02-04)
- Initial release with 8 domestic search engines
