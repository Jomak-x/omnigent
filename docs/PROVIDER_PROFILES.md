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

## Failover between accounts

With two accounts configured, a routing policy lets a new session start on the
one that can actually do the work:

```yaml
provider_routing:
  codex-native:
    order: [codex, codex-work]     # try in this order
    on: [quota_exhausted, authentication_required]   # optional; these are the defaults
```

Three rules govern it, and each exists because the opposite is worse than no
failover at all:

1. **An explicit pin is never overridden.** A session pinned to an account gets
   that account, exhausted or not. Routing is for the unpinned case only.
2. **A move needs a signal the provider actually reported** — a connection
   state, or a usage reading the vendor produced. `unknown` never counts as
   "spent", so an account that reports nothing is tried, not skipped.
3. **Order is configured, never guessed.** No `provider_routing:` block means no
   failover, and no cost: with no policy the selection path does not run, and no
   usage probe is taken.

Available triggers: `quota_exhausted`, `quota_nearly_exhausted`,
`authentication_required`, `provider_unavailable`, `misconfigured`. An unknown
one is a config error, not a silently ignored typo.

Cross-provider failover is not a separate mechanism — the policy names
providers, so moving between two Codex accounts and moving from Codex to a
gateway are the same thing. What routing never changes is the **model**: the
selection returns a provider name only, so model semantics cannot drift under a
session.

When a policy moves a session, the choice is written back as that session's own
provider pin. It is therefore visible wherever the session's provider is shown,
and a later resume stays on that account instead of being routed a second time.
Every move is logged with the account it left, why, and where it went.

### Mid-turn limit recovery

A running turn is not hot-swapped. Relaunching a native terminal under another
account would lose or replay in-flight state, so the failed turn still surfaces
the vendor's own error. Instead, a structured limit signal (`codexErrorInfo`
for native Codex, or the SDK's `RateLimitError` classification) triggers a
best-effort refresh over the existing runner → server → host usage route. The
host bypasses its per-account cache and asks the vendor again; only that vendor
reading can mark the account exhausted. No error-message matching and no
synthetic percentage are used.

An active routing policy records even its first selected account on the session,
so the refresh targets the account that actually failed. The next unpinned
launch then follows the existing launch-time policy and moves if the refreshed
vendor reading reports exhaustion. An explicitly pinned session remains pinned,
and a provider that does not report a spent state is never skipped.

## Setting up a second account by hand

```bash
CODEX_HOME=~/.codex-work codex login     # sign the second account in
```

Then add the `codex-work` entry above. Omnigent's readiness check reports that
account's own state, and the Providers screen shows its quota separately.
