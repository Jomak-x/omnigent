"""Browser regression for agent-scoped provider settings on a disposable host."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml
from playwright.sync_api import Page, expect

from tests._helpers.provider_setup_runtime import HOST_IDS, ProviderSetupRuntime

CLAUDE_NOTICE = (
    "Claude logins stored only in the OS Keychain are checked through guided sign-in, "
    "not detection."
)


@pytest.fixture
def provider_runtime(tmp_path: Path, built_spa: None) -> Iterator[ProviderSetupRuntime]:
    runtime = ProviderSetupRuntime(
        tmp_path / "provider-scoping", Path(__file__).resolve().parents[3]
    )
    runtime.start()
    try:
        yield runtime
    finally:
        runtime.stop()


def _config(runtime: ProviderSetupRuntime) -> dict:
    return yaml.safe_load((runtime.root / "host-a/config/config.yaml").read_text())


def _seed_cli_subscriptions(runtime: ProviderSetupRuntime) -> None:
    """Represent existing CLI logins in fixture config without running vendor CLIs."""
    path = runtime.root / "host-a/config/config.yaml"
    config = yaml.safe_load(path.read_text())
    config["providers"]["fixture-primary"].pop("default")
    config["providers"]["claude-subscription"] = {
        "kind": "subscription",
        "cli": "claude",
        "default": "anthropic",
    }
    config["providers"]["codex-subscription"] = {
        "kind": "subscription",
        "cli": "codex",
        "default": "openai",
    }
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    response = httpx.get(f"{runtime.url}/v1/hosts/{HOST_IDS[0]}/setup", timeout=10)
    response.raise_for_status()
    inventory = response.json()
    assert inventory["effective_defaults"]["anthropic"] == "claude-subscription"
    assert inventory["effective_defaults"]["openai"] == "codex-subscription"


def _agent(page: Page, agent_id: str) -> None:
    page.get_by_test_id(f"setup-agent-{agent_id}").click()


def _back(page: Page) -> None:
    page.get_by_role("button", name="Back to agents", exact=True).click()


def test_agent_scopes_defaults_detection_and_gateway_validation(
    page: Page, provider_runtime: ProviderSetupRuntime
) -> None:
    runtime = provider_runtime
    _seed_cli_subscriptions(runtime)
    page.goto(runtime.url + "/settings/providers")
    page.get_by_test_id("settings-providers-host").click()
    page.get_by_role("option", name="Fixture computer A · online", exact=True).click()
    expect(page.get_by_test_id("setup-agent-pi")).to_be_visible()

    _agent(page, "pi")
    expect(page.get_by_test_id("agent-provider-row-fixture-primary")).to_be_visible()
    expect(page.get_by_test_id("agent-provider-row-fixture-secondary")).to_be_visible()
    expect(page.get_by_test_id("agent-provider-row-claude-subscription")).to_have_count(0)
    expect(page.get_by_test_id("agent-provider-row-codex-subscription")).to_have_count(0)
    page.get_by_role("button", name="Pi subscription", exact=True).click()
    pi_row = page.get_by_test_id("agent-provider-row-pi-subscription")
    expect(pi_row.get_by_text("Used for new sessions", exact=True)).to_be_visible()
    assert _config(runtime)["providers"]["pi-subscription"]["default"] == "pi"

    with page.expect_request(f"**/v1/hosts/{HOST_IDS[0]}/setup/detect") as status_request:
        page.get_by_role("button", name="Check setup status", exact=True).click()
    assert status_request.value.post_data_json == {"harness": "pi-native"}
    expect(page.get_by_text("Ready according to setup · Fixture computer A")).to_be_visible()
    page.route(
        f"**/v1/hosts/{HOST_IDS[0]}/setup/detect",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body='{"detail":"Fixture status check unavailable"}',
        ),
        times=1,
    )
    page.get_by_role("button", name="Check setup status", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Fixture status check unavailable")
    expect(page.get_by_text("Ready according to setup · Fixture computer A")).to_have_count(0)

    page.get_by_role("button", name="Find credentials on this computer").click()
    results = page.get_by_test_id("provider-detection-results")
    expect(results).to_be_visible()
    expect(results).not_to_contain_text(CLAUDE_NOTICE)

    _back(page)
    _agent(page, "codex")
    codex_row = page.get_by_test_id("agent-provider-row-codex-subscription")
    expect(codex_row.get_by_text("Used for new sessions", exact=True)).to_be_visible()
    expect(page.get_by_test_id("agent-provider-row-claude-subscription")).to_have_count(0)
    expect(page.get_by_test_id("agent-provider-row-pi-subscription")).to_have_count(0)
    expect(page.get_by_test_id("provider-detection-results")).not_to_contain_text(CLAUDE_NOTICE)

    _back(page)
    _agent(page, "claude")
    claude_row = page.get_by_test_id("agent-provider-row-claude-subscription")
    expect(claude_row.get_by_text("Used for new sessions", exact=True)).to_be_visible()
    expect(page.get_by_test_id("agent-provider-row-codex-subscription")).to_have_count(0)
    expect(page.get_by_test_id("agent-provider-row-pi-subscription")).to_have_count(0)
    expect(page.get_by_test_id("provider-detection-results")).to_contain_text(CLAUDE_NOTICE)

    _back(page)
    _agent(page, "opencode")
    expect(page.get_by_test_id("provider-detection-results")).to_have_count(0)
    expect(page.get_by_role("button", name="Find credentials on this computer")).to_have_count(0)
    expect(page.locator("body")).not_to_contain_text(CLAUDE_NOTICE)

    _back(page)
    _agent(page, "pi")
    page.get_by_role("button", name="Compatible gateway", exact=True).click()
    save = page.get_by_role("button", name="Save gateway", exact=True)
    expect(save).to_be_disabled()
    page.get_by_label("Gateway name", exact=True).fill("pi-fixture-gateway")
    page.get_by_label("Base URL", exact=True).fill("javascript:invalid")
    page.get_by_label("OpenAI model", exact=True).fill("fixture-model")
    page.get_by_label("API key or token", exact=True).fill("fixture-only-secret")
    expect(save).to_be_enabled()
    save.click()
    expect(page.get_by_role("alert")).to_contain_text("invalid setup configuration")
    assert "pi-fixture-gateway" not in _config(runtime)["providers"]

    page.get_by_label("Base URL", exact=True).fill(f"http://127.0.0.1:{runtime.mock_ports[1]}/v1")
    page.route(
        f"**/v1/hosts/{HOST_IDS[0]}/setup/actions",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body='{"detail":"Fixture save temporarily unavailable"}',
        ),
        times=1,
    )
    save.click()
    expect(page.get_by_role("alert")).to_contain_text("Fixture save temporarily unavailable")
    expect(page.get_by_test_id("settings-providers-host")).to_contain_text("Fixture computer A")
    assert "pi-fixture-gateway" not in _config(runtime)["providers"]
    assert (
        "pi-fixture-gateway"
        not in yaml.safe_load((runtime.root / "host-b/config/config.yaml").read_text())[
            "providers"
        ]
    )

    save.click()
    gateway = page.get_by_test_id("agent-provider-row-pi-fixture-gateway")
    expect(gateway).to_be_visible()
    gateway.get_by_role("button", name="Use for new Pi sessions", exact=True).click()
    expect(gateway.get_by_text("Used for new sessions", exact=True)).to_be_visible()
    page.reload()
    _agent(page, "pi")
    expect(page.get_by_test_id("agent-provider-row-pi-fixture-gateway")).to_contain_text(
        "Used for new sessions"
    )
    saved = _config(runtime)
    assert saved["providers"]["pi-fixture-gateway"]["default"] == "pi"
    response = httpx.get(f"{runtime.url}/v1/hosts/{HOST_IDS[0]}/setup", timeout=10)
    response.raise_for_status()
    assert response.json()["effective_defaults"] == {
        "anthropic": "claude-subscription",
        "openai": "codex-subscription",
        "gemini": None,
        "pi": "pi-fixture-gateway",
    }
    assert "default" not in saved["providers"]["pi-subscription"]
    assert "fixture-only-secret" not in json.dumps(saved)
