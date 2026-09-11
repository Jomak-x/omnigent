# Provider settings end-to-end test

Build the current SPA, then run:

```sh
cd web
pnpm run build
cd ..
env -i PATH=/usr/bin:/bin LANG=en_US.UTF-8 \
  OMNIGENT_DISABLE_KEYRING=1 \
  PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
  .venv/bin/python tests/e2e_ui/providers/run.py \
  --state /tmp/provider-settings-fresh-run \
  --recordings /tmp/provider-settings-recordings
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

All application children boot through the helper's fail-closed guard. Their
environment is built from scratch; `HOME` and `CODEX_HOME` are never repurposed.
The guard blocks Keychain calls, ambient home access, non-fixture sockets, and
subprocesses other than the exact Python runner and SDK harness commands.
Configuration, credentials, data, and workspaces are disposable. Model-catalog
lookup is disabled. CLI installation/readiness and credential discovery are
controlled fixtures; this test does not prove a vendor CLI login or installation.

For a human check, open the fixture URL printed by a launcher, visit
**Settings → Providers**, explicitly choose **Fixture computer A**, add a local
gateway, and reload. Choose **Fixture computer B** and confirm that connection
is absent. Mock request ledgers identify which endpoint a real SDK session used.
