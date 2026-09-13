# Provider settings end-to-end fixtures

Build the current SPA, then run:

```sh
cd web
pnpm run build
cd ..
env -i PATH=/usr/bin:/bin LANG=en_US.UTF-8 \
  OMNIGENT_DISABLE_KEYRING=1 \
  PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
  .venv/bin/python tests/e2e_ui/providers/run.py \
  --state "$PWD/.provider-settings-evidence/defaults-state" \
  --recordings "$PWD/.provider-settings-evidence/defaults-recordings"
```

The test starts a real server, two real hosts, real provider configuration and
fallback secret stores, and an actual `openai-agents` SDK subprocess. Two local
OpenAI-compatible endpoints keep separate request ledgers. It holds provider A's
request while the browser saves a new default, proves a new session calls B,
then releases and continues the original A session without changing its runner.
Browser controls also verify selected-host persistence, reload, secret omission,
and removal. Use a new state directory for each run. The standalone driver loads
only this test module, avoiding unrelated repository conftests in its browser
process.

Use the same clean environment and SPA build for these standalone drivers,
replacing `run.py` above and choosing fresh state and recording paths:

- `run_scoping.py` checks the read-only overview, light/dark appearance, Pi
  compatibility, per-agent defaults and detection messages, rejected saves,
  save/reload, explicit Antigravity status, and retention of an offline selected
  host. Subscription entries are seeded only in disposable host configuration.
- `run_mutations.py` adds a masked catalog key in the browser, then exercises
  host API replacement, advanced-field preservation, owned/shared secret
  cleanup, provider and harness controls, ACP add/remove and import fingerprint
  validation, and rejection of malformed configuration before secret storage.
- `run_guided.py` additionally requires `--tmux /absolute/path/to/reviewed/tmux`.
  It runs a dummy vendor command in a real tmux terminal, checks rendered prompt
  pixels, reconnect without input replay, completion and scoped cancellation,
  rejected execution parameters and conflicting operations, and terminal-marker
  absence from application logs and the database. Add `--timeout-test` with new
  paths for the separate timeout/cleanup journey.

These runners stop their fixture processes when the journey finishes. No vendor
login is attempted; recorded device codes and terminal prompts are fake.

All application children boot through the helper's fail-closed guard. Their
environment is built from scratch; `HOME` and `CODEX_HOME` are never repurposed.
The guard blocks Keychain calls, ambient home access, non-fixture sockets, and
subprocesses other than the exact Python runner and SDK harness commands. The
guided fixture additionally allows its reviewed tmux binary and dummy pane
program on private fixture sockets.
Configuration, credentials, data, and workspaces are disposable. Model-catalog
lookup is disabled. CLI installation/readiness and credential discovery are
controlled fixtures; this test does not prove a vendor CLI login or installation.

For native Electron, the checkout also needs the dependencies under
`web/electron/`, including Playwright and Electron. From the repository root:

```sh
PROVIDER_ELECTRON_EVIDENCE="$PWD/.provider-settings-evidence/electron" \
  node tests/e2e_ui/providers/run_electron.cjs
```

The launcher supplies a clean environment to the guarded backend and native
shell. It checks gateway save, default selection and reload, and records light
and dark screenshots. The shell uses the production renderer with fixture
replacements for desktop process management, updates, login-shell lookup and
protocol registration; this does not validate desktop lifecycle behavior.

For a human check, add `PROVIDER_ELECTRON_HOLD_MS=300000` to that command to keep
the fixture open for five minutes after the automated journey. In
**Settings → Providers**, choose **Fixture computer A**, open Codex and confirm
`electron-fixture-gateway` is marked **Used for new sessions** after reload.
Choose **Fixture computer B** and confirm that connection is absent. The launcher
closes the shell and backend after the hold. Use a new evidence directory for
each Electron run. Mock request ledgers from `run.py` identify which endpoint a
real SDK session used; none of these fixtures proves real-vendor authentication.
