"""A Codex launch must bridge auth from the home its provider names.

These are the tests that make ``cli_home`` real: without them a second account
could be configured and every session would still read the first account's
``auth.json``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import omnigent.codex_native_app_server as app_server
from omnigent.onboarding.provider_config import load_providers


def _entry(raw: dict[str, object], name: str = "codex-work"):
    return load_providers({"providers": {name: raw}})[name]


def _subscription(cli_home: str | None) -> dict[str, object]:
    row: dict[str, object] = {"kind": "subscription", "cli": "codex"}
    if cli_home is not None:
        row["cli_home"] = cli_home
    return row


def test_a_logged_in_second_account_launches_against_its_own_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_home = tmp_path / "codex-work"
    work_home.mkdir()
    (work_home / "auth.json").write_text("{}")
    seen: list[Path] = []

    def _has_credential(path: Path) -> bool:
        seen.append(path)
        return path == work_home / "auth.json"

    monkeypatch.setattr("omnigent.onboarding.ambient.codex_auth_has_credential", _has_credential)

    launch = app_server._resolve_subscription_launch(
        _entry(_subscription(str(work_home))), None, {}
    )

    # The login check read the account's own auth.json, and the launch carries
    # that home forward so the session bridges from it.
    assert seen == [work_home / "auth.json"]
    assert launch.cli_home == str(work_home)


def test_a_provider_naming_no_home_keeps_the_previous_behaviour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_home = tmp_path / "default-codex"
    default_home.mkdir()
    monkeypatch.setattr(
        "omnigent.inner.codex_executor._codex_home_config_source_from_env",
        lambda: default_home,
    )
    monkeypatch.setattr(
        "omnigent.onboarding.ambient.codex_auth_has_credential",
        lambda path: path == default_home / "auth.json",
    )

    launch = app_server._resolve_subscription_launch(_entry(_subscription(None)), None, {})

    assert launch.cli_home is None


def test_a_logged_out_second_account_does_not_borrow_the_default_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure mode this guards: reading the *other* account's login."""
    work_home = tmp_path / "codex-work"
    work_home.mkdir()
    default_home = tmp_path / "default-codex"
    default_home.mkdir()
    (default_home / "auth.json").write_text("{}")
    monkeypatch.setattr(
        "omnigent.inner.codex_executor._codex_home_config_source_from_env",
        lambda: default_home,
    )
    monkeypatch.setattr(
        "omnigent.onboarding.ambient.codex_auth_has_credential",
        lambda path: path == default_home / "auth.json",
    )

    launch = app_server._resolve_subscription_launch(
        _entry(_subscription(str(work_home))), None, {}
    )

    # No other provider can route, so this stays on Codex's own login — but
    # pinned to the work home, not silently promoted to the personal account.
    assert launch.cli_home == str(work_home)
    assert "no usable Codex" in launch.summary


def test_a_cli_config_provider_carries_its_home(tmp_path: Path) -> None:
    launch = app_server._codex_provider_launch(
        _entry(
            {
                "kind": "cli-config",
                "cli": "codex",
                "model_provider": "Databricks",
                "cli_home": str(tmp_path / "gateway-home"),
            }
        ),
        None,
    )

    assert launch is not None
    assert launch.cli_home == str(tmp_path / "gateway-home")


def test_the_app_server_bridges_from_the_launch_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_home = tmp_path / "codex-work"
    server = app_server.build_codex_native_server(
        socket_path=tmp_path / "s.sock",
        codex_home=tmp_path / "private",
        cwd=tmp_path,
        model=None,
        profile=None,
        bridge_dir=tmp_path / "bridge",
        codex_path="/usr/bin/codex",
        config_source_home=work_home,
    )

    assert server.config_source_home == work_home


def test_the_app_server_without_a_launch_home_resolves_the_process_home(tmp_path: Path) -> None:
    server = app_server.build_codex_native_server(
        socket_path=tmp_path / "s.sock",
        codex_home=tmp_path / "private",
        cwd=tmp_path,
        model=None,
        profile=None,
        bridge_dir=tmp_path / "bridge",
        codex_path="/usr/bin/codex",
    )

    assert server.config_source_home is None


def test_readiness_judges_the_account_the_default_provider_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import omnigent.codex_native as codex_native

    work_home = tmp_path / "codex-work"
    monkeypatch.setattr(
        "omnigent.onboarding.provider_config.load_config",
        lambda: {
            "providers": {
                "codex-work": {
                    "kind": "subscription",
                    "cli": "codex",
                    "cli_home": str(work_home),
                    "default": "openai",
                }
            }
        },
    )

    source = codex_native._resolve_codex_auth_source()

    assert source.auth_path == work_home / "auth.json"
    assert source.config_path == work_home / "config.toml"


def test_readiness_falls_back_when_no_provider_names_a_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import omnigent.codex_native as codex_native

    default_home = tmp_path / "default-codex"
    monkeypatch.setattr(
        "omnigent.onboarding.provider_config.load_config",
        lambda: {"providers": {}},
    )
    monkeypatch.setattr(
        "omnigent.inner.codex_executor._codex_home_config_source_from_env",
        lambda: default_home,
    )

    source = codex_native._resolve_codex_auth_source()

    assert source.auth_path == default_home / "auth.json"


def test_a_spec_named_provider_uses_its_own_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An agent spec that names a provider must launch on that account."""
    work_home = tmp_path / "codex-work"
    work_home.mkdir()
    (work_home / "auth.json").write_text("{}")
    entry = _entry(_subscription(str(work_home)))
    monkeypatch.setattr(
        app_server, "_resolve_provider_for_build", lambda *a, **k: entry, raising=False
    )
    monkeypatch.setattr(
        "omnigent.runtime.workflow._resolve_provider_for_build", lambda *a, **k: entry
    )
    seen: list[Path] = []

    def _has_credential(path: Path) -> bool:
        seen.append(path)
        return True

    monkeypatch.setattr("omnigent.onboarding.ambient.codex_auth_has_credential", _has_credential)

    class _Executor:
        auth = object()
        profile = None
        config: dict[str, object] = {}

    class _Spec:
        executor = _Executor()

    launch = app_server.resolve_native_codex_launch(model=None, spec=_Spec())  # type: ignore[arg-type]

    assert launch.cli_home == str(work_home)
    assert seen == [work_home / "auth.json"]
