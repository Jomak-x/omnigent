"""Tests for the non-secret provider inventory."""

from __future__ import annotations

import pytest

from omnigent.onboarding.ambient import DetectedProvider
from omnigent.onboarding.provider_config import FamilyConfig, ProviderEntry
from omnigent.onboarding.provider_inventory import (
    ConnectionState,
    build_provider_inventory,
    provider_capabilities,
    provider_connection_state,
)


def test_inventory_combines_configured_and_detected_providers_without_secrets() -> None:
    config: dict[str, object] = {
        "providers": {
            "work": {
                "kind": "gateway",
                "default": "openai",
                "openai": {
                    "base_url": "https://gateway.example/v1",
                    "api_key": "top-secret-value",
                    "models": {"default": "company-model"},
                },
            }
        }
    }
    detected = [
        DetectedProvider(
            name="claude",
            kind="subscription",
            family="anthropic",
            source="claude CLI login",
        )
    ]

    rows = [
        entry.as_dict()
        for entry in build_provider_inventory(
            config,
            detected=detected,
            harness_readiness={"claude-native": "binary-missing"},
        )
    ]

    assert rows == [
        {
            "id": "claude",
            "display_name": "claude",
            "kind": "subscription",
            "origin": "detected",
            "source": "claude CLI login",
            "configuration_state": "valid",
            "error": None,
            "families": ["anthropic"],
            "surfaces": ["anthropic"],
            "default_for": ["anthropic"],
            "default_models": {},
            "cli": "claude",
            "profile": None,
            "model_provider": None,
            "capabilities": {
                "model_discovery": "supported",
                "usage_status": "unsupported",
                "multiple_profiles": "supported",
                "interactive_cli": "supported",
            },
            "connection_state": "unavailable",
            "connection_detail": "The claude CLI is not installed on this host.",
            "default_for_harnesses": ["claude-native", "claude-sdk"],
            "serves_harnesses": ["claude-native", "claude-sdk"],
        },
        {
            "id": "work",
            "display_name": "work",
            "kind": "gateway",
            "origin": "configured",
            "source": "config",
            "configuration_state": "valid",
            "error": None,
            "families": ["openai"],
            "surfaces": ["openai", "pi"],
            "default_for": ["openai"],
            "default_models": {"openai": "company-model"},
            "cli": None,
            "profile": None,
            "model_provider": None,
            "capabilities": {
                "model_discovery": "supported",
                "usage_status": "unsupported",
                "multiple_profiles": "unknown",
                "interactive_cli": "unsupported",
            },
            "connection_state": "connected",
            "connection_detail": "The openai credential resolves.",
            "default_for_harnesses": ["codex-native", "codex", "openai-agents", "pi-native", "pi"],
            "serves_harnesses": ["codex-native", "codex", "openai-agents", "pi-native", "pi"],
        },
    ]
    serialized = repr(rows)
    assert "top-secret-value" not in serialized
    assert "gateway.example" not in serialized


def test_databricks_inventory_exposes_profile_name_and_profile_capability() -> None:
    config: dict[str, object] = {
        "providers": {
            "analytics": {
                "kind": "databricks",
                "profile": "staging",
                "default": "openai",
            }
        }
    }

    [row] = [entry.as_dict() for entry in build_provider_inventory(config, detected=[])]

    assert row["profile"] == "staging"
    assert row["capabilities"] == {
        "model_discovery": "supported",
        "usage_status": "unsupported",
        "multiple_profiles": "supported",
        "interactive_cli": "unsupported",
    }


def test_bedrock_inventory_does_not_claim_unimplemented_discovery() -> None:
    provider = ProviderEntry(name="aws", kind="bedrock")

    assert provider_capabilities(provider).as_dict()["model_discovery"] == "unknown"


def test_inventory_keeps_malformed_entries_as_explicit_invalid_state() -> None:
    config: dict[str, object] = {
        "providers": {
            "broken": {"kind": "gateway", "api_key": "do-not-expose"},
            "codex": {"kind": "subscription", "cli": "codex"},
        }
    }

    rows = [entry.as_dict() for entry in build_provider_inventory(config, detected=[])]

    assert [row["id"] for row in rows] == ["broken", "codex"]
    assert rows[0]["configuration_state"] == "invalid"
    assert rows[0]["error"] == "Provider configuration is invalid. Reconfigure this provider."
    assert rows[1]["configuration_state"] == "valid"
    assert "do-not-expose" not in repr(rows)


def _subscription(cli: str = "codex") -> ProviderEntry:
    return ProviderEntry(name=cli, kind="subscription", cli=cli)


def _gateway(family: FamilyConfig, *, name: str = "work") -> ProviderEntry:
    return ProviderEntry(name=name, kind="gateway", families={"openai": family})


@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        (True, ConnectionState.CONNECTED),
        ("needs-auth", ConnectionState.AUTHENTICATION_REQUIRED),
        ("binary-missing", ConnectionState.UNAVAILABLE),
        (False, ConnectionState.UNAVAILABLE),
        ("version-too-low", ConnectionState.UNAVAILABLE),
    ],
)
def test_cli_provider_state_comes_from_the_cached_readiness_map(
    availability: object, expected: ConnectionState
) -> None:
    connection = provider_connection_state(
        _subscription(),
        harness_readiness={"codex-native": availability},  # type: ignore[dict-item]
    )

    assert connection.state is expected
    assert connection.detail


def test_cli_provider_without_a_readiness_map_reports_unknown_not_a_guess() -> None:
    # A host that never reported readiness must not be rendered as broken.
    assert provider_connection_state(_subscription()).state is ConnectionState.UNKNOWN
    assert (
        provider_connection_state(_subscription(), harness_readiness={}).state
        is ConnectionState.UNKNOWN
    )


def test_unset_env_credential_reads_as_authentication_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OMNIGENT_TEST_PROVIDER_KEY", raising=False)
    provider = _gateway(
        FamilyConfig(
            base_url="https://gateway.example/v1", api_key_ref="env:OMNIGENT_TEST_PROVIDER_KEY"
        )
    )

    connection = provider_connection_state(provider)

    assert connection.state is ConnectionState.AUTHENTICATION_REQUIRED
    assert "OMNIGENT_TEST_PROVIDER_KEY" in connection.detail


def test_set_env_credential_reads_as_connected_without_leaking_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OMNIGENT_TEST_PROVIDER_KEY", "sk-do-not-expose")
    provider = _gateway(
        FamilyConfig(
            base_url="https://gateway.example/v1", api_key_ref="env:OMNIGENT_TEST_PROVIDER_KEY"
        )
    )

    connection = provider_connection_state(provider)

    assert connection.state is ConnectionState.CONNECTED
    assert "sk-do-not-expose" not in connection.detail


def test_unset_endpoint_variable_is_misconfigured_not_an_auth_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OMNIGENT_TEST_PROVIDER_URL", raising=False)
    monkeypatch.setenv("OMNIGENT_TEST_PROVIDER_KEY", "sk-live")
    provider = _gateway(
        FamilyConfig(
            base_url="$OMNIGENT_TEST_PROVIDER_URL",
            api_key_ref="env:OMNIGENT_TEST_PROVIDER_KEY",
        )
    )

    assert provider_connection_state(provider).state is ConnectionState.MISCONFIGURED


def test_auth_command_credentials_are_unknown_because_they_are_never_run() -> None:
    provider = _gateway(
        FamilyConfig(base_url="https://gateway.example/v1", auth_command="print-token")
    )

    assert provider_connection_state(provider).state is ConnectionState.UNKNOWN


def test_a_broken_family_outranks_a_working_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # The launch that would fail is the state worth surfacing.
    monkeypatch.delenv("OMNIGENT_TEST_MISSING_KEY", raising=False)
    provider = ProviderEntry(
        name="split",
        kind="gateway",
        families={
            "anthropic": FamilyConfig(base_url="https://a.example/v1", api_key="literal"),
            "openai": FamilyConfig(
                base_url="https://o.example/v1", api_key_ref="env:OMNIGENT_TEST_MISSING_KEY"
            ),
        },
    )

    connection = provider_connection_state(provider)

    assert connection.state is ConnectionState.AUTHENTICATION_REQUIRED
    assert "openai" in connection.detail


def test_a_locked_credential_store_reads_unknown_rather_than_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(ref: str) -> str:
        raise RuntimeError("keyring backend is locked")

    monkeypatch.setattr("omnigent.onboarding.provider_inventory.resolve_secret", _explode)
    provider = _gateway(
        FamilyConfig(base_url="https://gateway.example/v1", api_key_ref="keychain:anthropic")
    )

    assert provider_connection_state(provider).state is ConnectionState.UNKNOWN


def test_databricks_profile_missing_from_the_local_config_needs_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "omnigent.onboarding.databricks_config.list_databricks_profiles", lambda: ["prod"]
    )
    provider = ProviderEntry(name="analytics", kind="databricks", profile="staging")

    connection = provider_connection_state(provider)

    assert connection.state is ConnectionState.AUTHENTICATION_REQUIRED
    assert "staging" in connection.detail


def test_databricks_profile_present_without_the_sdk_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "omnigent.onboarding.databricks_config.list_databricks_profiles", lambda: ["staging"]
    )
    monkeypatch.setattr(
        "omnigent.onboarding.databricks_config.databricks_sdk_installed", lambda: False
    )
    provider = ProviderEntry(name="analytics", kind="databricks", profile="staging")

    assert provider_connection_state(provider).state is ConnectionState.UNAVAILABLE


def test_unparseable_provider_rows_are_misconfigured_rather_than_unknown() -> None:
    config: dict[str, object] = {"providers": {"broken": {"kind": "gateway", "api_key": "x"}}}

    [row] = [entry.as_dict() for entry in build_provider_inventory(config, detected=[])]

    assert row["connection_state"] == "misconfigured"
    assert row["connection_detail"]


def test_rows_name_the_harnesses_they_would_serve() -> None:
    # The picker must not re-derive harness→provider from families itself.
    config: dict[str, object] = {
        "providers": {
            "claude": {"kind": "subscription", "cli": "claude", "default": "anthropic"},
            "work": {
                "kind": "gateway",
                "default": "openai",
                "openai": {"base_url": "https://gateway.example/v1", "api_key": "k"},
            },
        }
    }

    rows = {row.provider_id: row for row in build_provider_inventory(config, detected=[])}

    assert rows["claude"].default_for_harnesses == ("claude-native", "claude-sdk")
    assert "codex-native" in rows["work"].default_for_harnesses
    assert "claude-native" not in rows["work"].default_for_harnesses


def test_a_provider_that_is_nobodys_default_names_no_harness() -> None:
    config: dict[str, object] = {
        "providers": {
            "spare": {
                "kind": "gateway",
                "openai": {"base_url": "https://spare.example/v1", "api_key": "k"},
            }
        }
    }

    [row] = build_provider_inventory(config, detected=[])

    assert row.default_for_harnesses == ()
