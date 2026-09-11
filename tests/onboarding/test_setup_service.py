"""Host setup operates on isolated config and never contacts a paid provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from omnigent.config import load_global_config, save_global_config
from omnigent.onboarding import ambient, secrets
from omnigent.onboarding import detected as _detected  # noqa: F401
from omnigent.onboarding import setup_service as service
from omnigent.onboarding.setup_schema import SETUP_ACTION_ADAPTER


@pytest.fixture(autouse=True)
def isolated_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNIGENT_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OMNIGENT_DISABLE_KEYRING", "1")
    monkeypatch.setattr(ambient, "detect_providers", lambda **_: [])
    from omnigent.onboarding import openclaw_config, providers

    monkeypatch.setattr(
        openclaw_config, "discover_openclaw_agents", lambda: openclaw_config.OpenClawDiscovery(())
    )
    monkeypatch.setattr(providers, "get_chat_models", lambda _: [])
    monkeypatch.setattr(providers, "default_chat_model", lambda _: None)


def apply(**values: object):
    return service.apply_setup_action(SETUP_ACTION_ADAPTER.validate_python(values))


def gateway(name: str = "gateway", **overrides: object):
    return apply(
        **{
            "action": "add_gateway",
            "name": name,
            "base_url": "https://gateway.example/v1",
            "secret": "TEST-SECRET",
            "families": ["openai"],
            "models": {"openai": "test-model"},
            "wire_api": "chat",
            **overrides,
        }
    )


def test_named_keys_keep_distinct_sources_and_vendor_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FIRST_FIXTURE_KEY", "first")
    monkeypatch.setenv("SECOND_FIXTURE_KEY", "second")
    apply(
        action="add_key", provider="openrouter", env_var="FIRST_FIXTURE_KEY", model="vendor/model"
    )
    apply(
        action="add_key",
        provider="openrouter",
        env_var="SECOND_FIXTURE_KEY",
        model="vendor/model2",
    )
    apply(action="add_key", provider="openrouter", env_var="FIRST_FIXTURE_KEY", model="updated")
    entries = load_global_config()["providers"]
    assert set(entries) == {"openrouter", "openrouter-2"}
    assert entries["openrouter"]["openai"]["base_url"] == "https://openrouter.ai/api/v1"
    assert entries["openrouter"]["openai"]["wire_api"] == "chat"
    assert entries["openrouter"]["openai"]["models"]["default"] == "updated"


def test_gateway_defaults_and_credential_update_preserve_advanced(tmp_path: Path):
    gateway()
    cfg = load_global_config()
    cfg["providers"]["gateway"]["openai"]["context_window"] = 200000
    cfg["providers"]["gateway"]["openai"]["models"]["fast"] = "fast-model"
    cfg["providers"]["gateway"]["future_setting"] = {"keep": True}
    save_global_config(cfg)
    gateway("second")
    apply(action="set_default", name="second", surface="openai")
    apply(
        action="update_provider_credential",
        name="gateway",
        families=["openai"],
        secret="NEW-SECRET",
    )
    cfg = load_global_config()
    assert cfg["providers"]["gateway"]["future_setting"] == {"keep": True}
    assert cfg["providers"]["gateway"]["openai"]["context_window"] == 200000
    assert cfg["providers"]["gateway"]["openai"]["models"]["fast"] == "fast-model"
    inventory = service.get_setup_inventory()
    assert inventory.effective_defaults["openai"] == "second"
    assert "TEST-SECRET" not in inventory.model_dump_json()
    assert "NEW-SECRET" not in (tmp_path / "config.yaml").read_text()


@pytest.mark.parametrize(
    "raw", ["[broken", "- sequence", "providers: invalid", "providers:\n  bad: 4"]
)
def test_malformed_config_rejected_before_secret_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
):
    path = tmp_path / "config.yaml"
    path.write_text(raw)
    monkeypatch.setattr(
        secrets, "store_secret", lambda *_: pytest.fail("secret write before validation")
    )
    with pytest.raises(ValueError, match="existing configuration"):
        gateway()
    assert path.read_text() == raw


@pytest.mark.parametrize(
    "overrides",
    [
        {"models": {}},
        {"base_url": "https://user:password@gateway.example"},
        {"base_url": "https://gateway.example?token=private"},
        {"secret": " "},
    ],
)
def test_invalid_gateway_never_writes(
    overrides: dict[str, object], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        secrets, "store_secret", lambda *_: pytest.fail("secret write before validation")
    )
    with pytest.raises(ValueError):
        gateway(**overrides)
    assert not load_global_config()


def test_passive_inventory_never_detects_resolves_or_fetches(monkeypatch: pytest.MonkeyPatch):
    gateway()
    monkeypatch.setattr(ambient, "detect_providers", lambda: pytest.fail("passive detection"))
    monkeypatch.setattr(secrets, "load_secret", lambda *_: pytest.fail("secret resolved"))
    assert service.get_setup_inventory().providers[0].name == "gateway"


def test_harness_keys_preserve_advanced_host_and_removal():
    save_global_config({"copilot": {"github_host": "enterprise.example", "future": 4}})
    apply(action="set_harness_key", harness="copilot", secret="fixture-token")
    apply(action="set_copilot_host", host="new.example")
    apply(action="remove_harness_key", harness="copilot")
    assert load_global_config()["copilot"] == {"github_host": "new.example", "future": 4}


def test_acp_edits_preserve_unknown_existing_fields():
    save_global_config(
        {"acp": {"future": True, "agents": [{"name": "Old", "command": "old --acp", "future": 3}]}}
    )
    apply(
        action="add_acp",
        name="New",
        command="new --acp",
        env_passthrough=["FIXTURE_TOKEN"],
        omnigent_mcp=False,
    )
    assert load_global_config()["acp"]["agents"][0]["future"] == 3
    apply(action="remove_acp", slug="new")
    assert load_global_config()["acp"] == {
        "future": True,
        "agents": [{"name": "Old", "command": "old --acp", "future": 3}],
    }


def test_detect_adopt_remove_dismiss_and_re_adopt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr(
        ambient,
        "detect_providers",
        lambda **_: [ambient.DetectedProvider("openai", "key", "openai", "$OPENAI_API_KEY")],
    )
    assert service.detect_setup_connections().providers[0].name == "openai"
    apply(action="adopt_detected", name="openai")
    apply(action="remove_provider", name="openai")
    assert service.get_setup_inventory().dismissed_detections == ["openai"]
    apply(action="adopt_detected", name="openai")
    assert service.get_setup_inventory().dismissed_detections == []


def test_pi_subscription_and_bedrock_compatibility():
    apply(action="subscription", cli="pi")
    apply(action="add_bedrock", model="bedrock-model", secret="bedrock-secret")
    cfg = service.get_setup_inventory()
    assert cfg.effective_defaults["pi"] == "pi-subscription"
    assert cfg.effective_defaults["anthropic"] == "bedrock"
    assert "pi" not in next(p for p in cfg.providers if p.name == "bedrock").default_scopes


def test_vendor_subscription_requires_successful_login():
    with pytest.raises(ValueError, match="vendor login"):
        apply(action="subscription", cli="codex")
    assert load_global_config() == {}


def test_opencode_model_clear():
    apply(action="set_opencode_model", model="provider/model")
    assert service.get_setup_inventory().harness_settings.opencode_model == "provider/model"
    apply(action="set_opencode_model", model=None)
    assert "opencode_model" not in load_global_config()


def test_failed_rotation_keeps_previous_secret_and_reference(monkeypatch: pytest.MonkeyPatch):
    gateway()
    before = load_global_config()
    old_ref = before["providers"]["gateway"]["openai"]["api_key_ref"]
    old_secret = secrets.load_secret(old_ref.removeprefix("keychain:"))
    monkeypatch.setattr(
        service.operations,
        "save_setup_settings",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("fixture failure")),
    )
    with pytest.raises(OSError, match="fixture failure"):
        apply(
            action="update_provider_credential",
            name="gateway",
            families=["openai"],
            secret="replacement",
        )
    assert load_global_config() == before
    assert secrets.load_secret(old_ref.removeprefix("keychain:")) == old_secret


def test_rotation_does_not_change_shared_sibling_credential():
    gateway()
    config = load_global_config()
    from copy import deepcopy

    sibling = deepcopy(config["providers"]["gateway"])
    sibling.pop("default", None)
    config["providers"]["sibling"] = sibling
    save_global_config(config)
    old_ref = sibling["openai"]["api_key_ref"]
    apply(
        action="update_provider_credential",
        name="gateway",
        families=["openai"],
        secret="replacement",
    )
    assert load_global_config()["providers"]["sibling"]["openai"]["api_key_ref"] == old_ref
    assert secrets.load_secret(old_ref.removeprefix("keychain:")) == "TEST-SECRET"


def test_remove_acp_skips_malformed_existing_entries():
    malformed = {"name": 3, "command": "invalid-agent"}
    save_global_config(
        {"acp": {"agents": [malformed, {"name": "Keep", "command": "valid-agent"}]}}
    )
    apply(action="remove_acp", slug="keep")
    assert load_global_config()["acp"]["agents"] == [malformed]


def test_import_previews_hide_arguments_and_reject_changed_commands(tmp_path: Path):
    import json

    source = tmp_path / "acpx.json"
    source.write_text(
        json.dumps(
            {
                "agents": {
                    "Fixture": {
                        "command": "fixture",
                        "args": ["--header", "Authorization: Bearer SECRET"],
                    }
                }
            }
        )
    )
    preview = service.detect_setup_connections(
        service.SetupDetectRequest(import_path=str(source), import_source="acpx")
    )
    assert "SECRET" not in preview.model_dump_json()
    assert preview.imports[0].command == "fixture (2 arguments hidden)"
    fingerprints = {p.name: p.fingerprint for p in preview.imports}
    source.write_text(json.dumps({"agents": {"Fixture": {"command": "changed"}}}))
    with pytest.raises(ValueError, match="changed"):
        apply(
            action="import_acp",
            source="acpx",
            path=str(source),
            names=["Fixture"],
            fingerprints=fingerprints,
        )
    current = service.detect_setup_connections(
        service.SetupDetectRequest(import_path=str(source), import_source="acpx")
    )
    apply(
        action="import_acp",
        source="acpx",
        path=str(source),
        names=["Fixture"],
        fingerprints={p.name: p.fingerprint for p in current.imports},
    )
    assert load_global_config()["acp"]["agents"][0]["command"] == "changed"


def test_passive_explicit_pi_cli_config_does_not_probe(monkeypatch: pytest.MonkeyPatch):
    from omnigent.onboarding import provider_config

    save_global_config(
        {
            "providers": {
                "custom": {
                    "kind": "cli-config",
                    "cli": "codex",
                    "model_provider": "Fixture",
                    "default": "pi",
                }
            }
        }
    )
    monkeypatch.setattr(
        provider_config, "_cli_config_serves_pi", lambda *_: pytest.fail("vendor probe")
    )
    inventory = service.get_setup_inventory()
    assert inventory.effective_defaults["pi"] == "custom"
    assert not inventory.pi_default_requires_detection


def test_invalid_acp_config_rejected_before_credential_write(monkeypatch: pytest.MonkeyPatch):
    save_global_config(
        {"acp": {"agents": [{"name": "Fixture", "command": "fixture", "omnigent_mcp": "invalid"}]}}
    )
    monkeypatch.setattr(
        secrets, "store_secret", lambda *_: pytest.fail("secret write before parse")
    )
    with pytest.raises(ValueError, match="existing configuration"):
        gateway()


def test_browser_detection_never_uses_claude_keychain_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(ambient, "_claude_login_detected", lambda: pytest.fail("Keychain probe"))
    monkeypatch.setattr(
        ambient, "_claude_credentials_path", lambda: tmp_path / "missing-claude.json"
    )
    monkeypatch.setattr(ambient, "_codex_auth_path", lambda: tmp_path / "missing-codex.json")
    monkeypatch.setattr(ambient, "claude_managed_gateway", lambda: (None, False))
    monkeypatch.setattr(ambient, "codex_config_detection", lambda: None)
    monkeypatch.setattr(ambient, "_ollama_reachable", lambda: False)
    ambient._detect_providers_now(allow_keychain=False)


@pytest.mark.parametrize(
    "old_ref, expected",
    [("keychain:openai-other", "openai-2"), ("keychain:openai-" + "a" * 32, "openai")],
)
def test_readding_named_key_recognizes_only_own_rotated_slots(old_ref: str, expected: str):
    save_global_config(
        {
            "providers": {
                "openai": {
                    "kind": "key",
                    "openai": {
                        "base_url": "https://api.openai.com/v1",
                        "api_key_ref": old_ref,
                        "models": {"default": "original"},
                    },
                }
            }
        }
    )
    result = apply(
        action="add_key", provider="openai", secret="fixture-replacement", model="updated"
    )
    assert result.message == f"Added {expected}"
    assert load_global_config()["providers"][expected]["openai"]["models"]["default"] == "updated"


def test_inline_harness_credentials_are_listed_without_resolving():
    save_global_config(
        {
            "cursor": {"api_key": "INLINE-SECRET"},
            "antigravity": {"api_key": "$FIXTURE_GEMINI"},
            "copilot": {"github_token": "INLINE-TOKEN"},
        }
    )
    inventory = service.get_setup_inventory()
    assert inventory.harness_settings.cursor_key_configured
    assert inventory.harness_settings.antigravity_key_configured
    assert inventory.harness_settings.copilot_key_configured
    assert "INLINE-SECRET" not in inventory.model_dump_json()
    assert "INLINE-TOKEN" not in inventory.model_dump_json()


def test_existing_unicode_provider_identifier_can_be_managed():
    name = "研究/代理:work"
    save_global_config(
        {
            "providers": {
                name: {
                    "kind": "key",
                    "openai": {
                        "base_url": "https://api.openai.com/v1",
                        "api_key_ref": "env:FIXTURE_UNUSED",
                    },
                }
            }
        }
    )
    apply(action="set_default", name=name, surface="openai")
    apply(action="update_provider_credential", name=name, families=["openai"], secret="fixture")
    assert service.get_setup_inventory().effective_defaults["openai"] == name
    apply(action="remove_provider", name=name)
    assert service.get_setup_inventory().providers == []
