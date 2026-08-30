# Multiple accounts per provider

Two accounts with the same vendor — a personal Codex login and a work one — are
one config change apart, because a provider entry can now name the CLI home it
authenticates from.

```yaml
providers:
  codex:                       # the personal account, unchanged
    kind: subscription
    cli: codex
    default: openai
  codex-work:
    kind: subscription
    cli: codex
    cli_home: ~/.codex-work    # this account's own credential root
```

`cli_home` accepts `~` and `$VAR` references, resolved when a launch uses them
rather than when the config is read, so the same file works across machines. An
unset variable **fails the launch** instead of quietly falling back: silently
authenticating as the other account is worse than not starting.

## Why a home, and not a "profile id"

Vendor CLIs keep their login in a fixed place — `~/.codex/auth.json`,
`~/.claude`, the macOS Keychain. There is no vendor-side notion of a named
profile to reference, so the only honest handle on "which account" is the
directory that holds its credentials. Omnigent already launches Codex with a
**private per-session `CODEX_HOME`** and bridges `auth.json` (symlinked, so
token refreshes propagate) and `config.toml` (copied, so an in-session `/model`
cannot mutate the shared file) from one source home. `cli_home` is simply which
source home that is. The isolation machinery did not need to change; it was
already there, pointed at a constant.

Credentials never move: the path stays on the host, the inventory keeps it in a
host-side-only field that `as_dict()` does not serialize, and nothing about a
credential reaches the frontend.

## What honours it today

| Path | Status |
|---|---|
| `codex-native` sessions (web / runner) | **Wired** — `NativeCodexLaunch.cli_home` → `CodexNativeAppServer.config_source_home` → the bridged home |
| `omnigent codex` (local TUI) | **Wired** — same launch object |
| Background session titles | **Wired** |
| Codex readiness (`needs-auth` vs signed in) | **Wired** — judged against the default provider's own home |
| Codex usage/quota reads | **Wired** — probed with that home, and cached per home so two accounts never serve each other's numbers |
| `claude-native` | **Not yet** — needs the same treatment for `CLAUDE_CONFIG_DIR`; `multiple_profiles` honestly reports `unsupported` for claude rather than promising a switch that would not happen |
| In-process `codex` SDK harness | **Not yet** — resolves its own home in `codex_executor.py` |

The capability flag follows the wiring: `ProviderCapabilities.multiple_profiles`
is `supported` only for `cli: codex` entries.

## What is deliberately not built yet

**Choosing a profile per session.** Today a session uses whichever provider is
the configured default for its harness. Picking one per session needs a
provider pin threaded from `SessionCreateRequest` → the existing
`session_overrides` JSON column (no migration required) → `session_init_protocol`
→ `resolve_native_codex_launch`, slotting in above "explicit per-family default
provider" in that function's documented precedence. That same seam is what
failover (T11) needs in order to move work between profiles, so it should be
built once, for both, rather than twice.

**Automatic failover between profiles.** With usage status (per account) and
profiles (per credential root) both in place, the remaining pieces are a routing
policy and a user-visible event ("Codex / Personal reached its usage limit; the
task moved to Codex / Work"). The error classification it needs already exists
in `omnigent/runtime/harnesses/_executor_adapter.py` — it maps structured
provider errors, so no string-matching on `"limit"` is required.

## Setting up a second account by hand

```bash
CODEX_HOME=~/.codex-work codex login     # sign the second account in
```

Then add the `codex-work` entry above. Omnigent's readiness check reports that
account's own state, and the Providers screen shows its quota separately.
