"""Non-secret provider inventory for host and UI status surfaces.

Every row carries an explicit :class:`ConnectionState` so a status surface
never has to render an open-ended spinner. The state is derived from local
information only — the harness readiness map the host already refreshes, a
credential reference that does or does not resolve, a Databricks profile
section that does or does not exist. No endpoint is contacted and no CLI is
spawned here, so ``connected`` means "everything this host can check locally
resolves", never "the vendor answered".
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from omnigent.env_credentials import expand_envvars_with_omnigent_prefix
from omnigent.errors import OmnigentError
from omnigent.harness_availability import (
    HARNESS_BINARY_MISSING,
    HARNESS_NEEDS_AUTH,
    HARNESS_VERSION_TOO_LOW,
    HarnessAvailability,
)
from omnigent.json_types import JsonObject
from omnigent.onboarding.ambient import DetectedProvider, detect_providers
from omnigent.onboarding.detected import effective_config_with_detected
from omnigent.onboarding.provider_config import (
    BEDROCK_KIND,
    CLI_CONFIG_KIND,
    DATABRICKS_KIND,
    GATEWAY_KIND,
    KEY_KIND,
    LOCAL_KIND,
    SUBSCRIPTION_KIND,
    FamilyConfig,
    ProviderEntry,
    load_config,
    load_providers,
    provider_families,
    resolve_secret,
)
from omnigent.spec.parser import check_unresolved_env_vars

_logger = logging.getLogger(__name__)


class CapabilitySupport(str, Enum):
    """Whether Omnigent currently exposes a provider capability."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider-level features, kept separate from harness capabilities."""

    model_discovery: CapabilitySupport
    usage_status: CapabilitySupport
    multiple_profiles: CapabilitySupport
    interactive_cli: CapabilitySupport

    def as_dict(self) -> JsonObject:
        """Return a JSON-safe capability view."""
        return {
            "model_discovery": self.model_discovery.value,
            "usage_status": self.usage_status.value,
            "multiple_profiles": self.multiple_profiles.value,
            "interactive_cli": self.interactive_cli.value,
        }


class ConnectionState(str, Enum):
    """How usable a provider is, as far as the host can tell locally.

    Deliberately explicit: a status surface renders one of these rather than
    an unbounded spinner. ``CONNECTING`` / ``TIMEOUT`` / ``ERROR`` describe a
    client's attempt to *fetch* the inventory and are produced by the caller
    (see the web ``providerFetchState`` helper), never by this module — a row
    that exists has already settled into one of the states below.
    """

    CONNECTED = "connected"
    AUTHENTICATION_REQUIRED = "authentication_required"
    MISCONFIGURED = "misconfigured"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderConnection:
    """A connection state plus the non-secret sentence explaining it."""

    state: ConnectionState
    detail: str


def _connection(state: ConnectionState, detail: str) -> ProviderConnection:
    return ProviderConnection(state=state, detail=detail)


# Readiness-map spelling whose availability describes each CLI-backed
# provider's credential. The map keys every accepted harness spelling, so a
# CLI without an entry here (a newer vendor) falls back to its own name and,
# failing that, reports ``unknown`` rather than guessing.
_CLI_READINESS_HARNESS: dict[str, str] = {
    "claude": "claude-native",
    "codex": "codex-native",
    "pi": "pi",
}


def _cli_connection(
    provider: ProviderEntry,
    readiness: Mapping[str, HarnessAvailability] | None,
) -> ProviderConnection:
    """Derive a CLI-backed provider's state from the cached readiness map.

    The map is the one the host daemon already refreshes on its own schedule,
    so this adds no probe of its own. ``True`` means the harness that consumes
    this provider resolved *a* usable credential on this host — for a
    subscription row that is normally the CLI's own login, but an omnigent-managed
    key serving the same family also satisfies it, so the detail sentence says
    "a usable credential" rather than naming the login.
    """
    cli = provider.cli
    if cli is None:  # a malformed entry that parsed anyway
        return _connection(
            ConnectionState.UNKNOWN,
            "This provider does not name the CLI that carries its credential.",
        )
    if readiness is None:
        return _connection(
            ConnectionState.UNKNOWN,
            "This host has not reported harness readiness yet.",
        )
    availability = readiness.get(_CLI_READINESS_HARNESS.get(cli, cli))
    if availability is True:
        return _connection(
            ConnectionState.CONNECTED,
            f"The {cli} CLI is installed and reports a usable credential.",
        )
    if availability is None:
        return _connection(
            ConnectionState.UNKNOWN,
            f"This host reports no readiness for the {cli} CLI.",
        )
    if availability == HARNESS_NEEDS_AUTH:
        return _connection(
            ConnectionState.AUTHENTICATION_REQUIRED,
            f"The {cli} CLI is installed but has no credential yet. "
            "Sign in on this host to use it.",
        )
    if availability == HARNESS_VERSION_TOO_LOW:
        return _connection(
            ConnectionState.UNAVAILABLE,
            f"The installed {cli} CLI is older than the version this harness requires.",
        )
    if availability is False or availability == HARNESS_BINARY_MISSING:
        return _connection(
            ConnectionState.UNAVAILABLE,
            f"The {cli} CLI is not installed on this host.",
        )
    return _connection(
        ConnectionState.UNKNOWN,
        f"This host reports an unrecognized readiness state for the {cli} CLI.",
    )


def _reference_resolves(key: str, value: str) -> bool:
    """Whether a ``$VAR`` reference expands, without keeping the result."""
    try:
        check_unresolved_env_vars(key, expand_envvars_with_omnigent_prefix(value))
    except OmnigentError:
        return False
    return True


def _family_connection(
    provider_name: str, family_name: str, raw: FamilyConfig
) -> ProviderConnection:
    """Derive one family's state from its endpoint and credential references.

    Resolution is local: an environment variable is read from the environment
    and a ``keychain:`` reference from the host's own secret store. The secret
    value is discarded immediately — only whether it resolved is reported. An
    ``auth_command`` is never executed here (it is a per-launch subprocess), so
    it settles as ``unknown``.
    """
    prefix = f"providers.{provider_name}.{family_name}"
    if not _reference_resolves(f"{prefix}.base_url", raw.base_url):
        return _connection(
            ConnectionState.MISCONFIGURED,
            f"The {family_name} endpoint references an environment variable that is not set.",
        )
    if raw.api_key is not None:
        if not _reference_resolves(f"{prefix}.api_key", raw.api_key):
            return _connection(
                ConnectionState.AUTHENTICATION_REQUIRED,
                f"The {family_name} API key references an environment variable that is not set.",
            )
        return _connection(ConnectionState.CONNECTED, f"The {family_name} credential resolves.")
    if raw.api_key_ref is not None:
        try:
            resolve_secret(raw.api_key_ref)
        except OmnigentError:
            return _connection(
                ConnectionState.AUTHENTICATION_REQUIRED,
                f"The {family_name} credential ({raw.api_key_ref}) is not available on this host.",
            )
        except Exception:  # a locked keyring must not masquerade as "no credential"
            _logger.exception("Provider %s: credential lookup failed", provider_name)
            return _connection(
                ConnectionState.UNKNOWN,
                f"The {family_name} credential store could not be read on this host.",
            )
        return _connection(ConnectionState.CONNECTED, f"The {family_name} credential resolves.")
    if raw.auth_command is not None:
        return _connection(
            ConnectionState.UNKNOWN,
            f"The {family_name} credential comes from an auth command, run at launch time.",
        )
    return _connection(
        ConnectionState.MISCONFIGURED,
        f"The {family_name} family declares no credential source.",
    )


# Worst-first: one broken family is the state worth surfacing, because that is
# the launch that will fail. ``unknown`` outranks ``connected`` so a provider is
# never reported ready on the strength of its other family alone.
_FAMILY_STATE_PRECEDENCE: tuple[ConnectionState, ...] = (
    ConnectionState.MISCONFIGURED,
    ConnectionState.AUTHENTICATION_REQUIRED,
    ConnectionState.UNKNOWN,
    ConnectionState.CONNECTED,
)


def _families_connection(provider: ProviderEntry) -> ProviderConnection:
    """Reduce a provider's per-family states to the one worth showing."""
    results = [
        _family_connection(provider.name, family, provider.families[family])
        for family in sorted(provider.families)
    ]
    if not results:
        return _connection(
            ConnectionState.MISCONFIGURED,
            "This provider serves no model family.",
        )
    for state in _FAMILY_STATE_PRECEDENCE:
        for result in results:
            if result.state is state:
                return result
    return results[0]


def _databricks_connection(provider: ProviderEntry) -> ProviderConnection:
    """Check the Databricks profile section and the optional SDK extra."""
    from omnigent.onboarding.databricks_config import (
        databricks_sdk_installed,
        list_databricks_profiles,
    )

    profile = provider.profile
    if profile is None:
        return _connection(
            ConnectionState.MISCONFIGURED,
            "This Databricks provider names no profile.",
        )
    try:
        profiles = list_databricks_profiles()
    except Exception:  # an unreadable config must not read as "no profile"
        _logger.exception("Provider %s: reading ~/.databrickscfg failed", provider.name)
        return _connection(
            ConnectionState.UNKNOWN,
            "The Databricks configuration file could not be read on this host.",
        )
    if profile not in profiles:
        return _connection(
            ConnectionState.AUTHENTICATION_REQUIRED,
            f"Profile {profile!r} is not declared in ~/.databrickscfg on this host.",
        )
    if not databricks_sdk_installed():
        return _connection(
            ConnectionState.UNAVAILABLE,
            "The databricks extra is not installed on this host.",
        )
    return _connection(
        ConnectionState.CONNECTED,
        f"Profile {profile!r} is configured on this host.",
    )


def provider_connection_state(
    provider: ProviderEntry,
    *,
    harness_readiness: Mapping[str, HarnessAvailability] | None = None,
) -> ProviderConnection:
    """Return the explicit connection state for a parsed provider.

    :param provider: The parsed provider entry.
    :param harness_readiness: The host's cached harness readiness map. ``None``
        (a host that has not reported one) yields ``unknown`` for CLI-backed
        providers rather than a guess.
    :returns: The state plus a non-secret sentence a UI can render verbatim.
    """
    try:
        if provider.kind in (SUBSCRIPTION_KIND, CLI_CONFIG_KIND):
            return _cli_connection(provider, harness_readiness)
        if provider.kind == DATABRICKS_KIND:
            return _databricks_connection(provider)
        if provider.kind in (KEY_KIND, GATEWAY_KIND, LOCAL_KIND):
            return _families_connection(provider)
        if provider.kind == BEDROCK_KIND:
            return _connection(
                ConnectionState.UNKNOWN,
                "Bedrock credentials resolve from the AWS credential chain at launch time.",
            )
    except Exception:  # a status read must always settle on a state
        _logger.exception("Provider %s: connection state check failed", provider.name)
        return _connection(
            ConnectionState.UNKNOWN,
            "This provider's configuration could not be checked on this host.",
        )
    return _connection(
        ConnectionState.UNKNOWN,
        f"Omnigent cannot check a {provider.kind} provider's credential locally.",
    )


@dataclass(frozen=True)
class ProviderInventoryEntry:
    """A configured or ambient provider without credential material."""

    provider_id: str
    display_name: str
    kind: str
    origin: str
    source: str
    configuration_state: str
    error: str | None
    families: tuple[str, ...]
    surfaces: tuple[str, ...]
    default_for: tuple[str, ...]
    default_models: dict[str, str]
    cli: str | None
    profile: str | None
    model_provider: str | None
    capabilities: ProviderCapabilities
    connection_state: ConnectionState
    connection_detail: str

    def as_dict(self) -> JsonObject:
        """Return the public API representation."""
        return {
            "id": self.provider_id,
            "display_name": self.display_name,
            "kind": self.kind,
            "origin": self.origin,
            "source": self.source,
            "configuration_state": self.configuration_state,
            "error": self.error,
            "families": list(self.families),
            "surfaces": list(self.surfaces),
            "default_for": list(self.default_for),
            "default_models": dict(self.default_models),
            "cli": self.cli,
            "profile": self.profile,
            "model_provider": self.model_provider,
            "capabilities": self.capabilities.as_dict(),
            "connection_state": self.connection_state.value,
            "connection_detail": self.connection_detail,
        }


_DISCOVERABLE_KINDS = frozenset({KEY_KIND, GATEWAY_KIND, LOCAL_KIND, DATABRICKS_KIND})


def _unknown_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        model_discovery=CapabilitySupport.UNKNOWN,
        usage_status=CapabilitySupport.UNKNOWN,
        multiple_profiles=CapabilitySupport.UNKNOWN,
        interactive_cli=CapabilitySupport.UNKNOWN,
    )


def provider_capabilities(provider: ProviderEntry) -> ProviderCapabilities:
    """Derive conservative capabilities from an existing provider entry."""
    known_cli_discovery = (
        provider.kind == SUBSCRIPTION_KIND and provider.cli in {"claude", "codex", "pi"}
    ) or (provider.kind == CLI_CONFIG_KIND and provider.cli == "codex")
    model_discovery = (
        CapabilitySupport.SUPPORTED
        if (provider.kind in _DISCOVERABLE_KINDS or known_cli_discovery)
        else CapabilitySupport.UNKNOWN
    )
    interactive_cli = (
        CapabilitySupport.SUPPORTED
        if provider.kind in {SUBSCRIPTION_KIND, CLI_CONFIG_KIND}
        else CapabilitySupport.UNSUPPORTED
    )
    if provider.kind == DATABRICKS_KIND:
        multiple_profiles = CapabilitySupport.SUPPORTED
    elif provider.kind == SUBSCRIPTION_KIND:
        multiple_profiles = CapabilitySupport.UNSUPPORTED
    else:
        multiple_profiles = CapabilitySupport.UNKNOWN
    return ProviderCapabilities(
        model_discovery=model_discovery,
        # Only Codex exposes its own quota locally (its app-server answers
        # ``account/rateLimits/read``). Every other integration reports nothing
        # a status surface could show without inventing it.
        usage_status=(
            CapabilitySupport.SUPPORTED
            if provider.kind in (SUBSCRIPTION_KIND, CLI_CONFIG_KIND) and provider.cli == "codex"
            else CapabilitySupport.UNSUPPORTED
        ),
        multiple_profiles=multiple_profiles,
        interactive_cli=interactive_cli,
    )


def build_provider_inventory(
    config: dict[str, object] | None = None,
    *,
    detected: list[DetectedProvider] | None = None,
    harness_readiness: Mapping[str, HarnessAvailability] | None = None,
) -> list[ProviderInventoryEntry]:
    """Return configured plus ambient providers with an explicit state each.

    :param config: The effective Omnigent config; loaded from disk when omitted.
    :param detected: Ambient providers; detected when omitted.
    :param harness_readiness: The host's cached harness readiness map, used for
        CLI-backed rows so this call spawns no probe of its own.
    :returns: One row per provider, each carrying a settled
        :class:`ConnectionState` — never an open-ended "still checking".
    """
    if config is None:
        config = dict(load_config())
    if detected is None:
        detected = detect_providers()

    explicit_raw = config.get("providers")
    explicit_names = set(explicit_raw) if isinstance(explicit_raw, dict) else set()
    detected_by_name = {item.name: item for item in detected}
    try:
        effective = effective_config_with_detected(config, detected)
    except Exception:  # one malformed explicit entry must not erase every row
        effective = config
    raw_providers = effective.get("providers")
    if not isinstance(raw_providers, dict):
        return []

    inventory: list[ProviderInventoryEntry] = []
    for raw_name, raw_provider in raw_providers.items():
        name = str(raw_name)
        ambient = detected_by_name.get(name)
        origin = "configured" if name in explicit_names else "detected"
        source = ambient.source if origin == "detected" and ambient is not None else "config"
        try:
            parsed = load_providers({"providers": {name: raw_provider}})
            provider = parsed.get(name)
        except Exception:
            provider = None
        if provider is None:
            inventory.append(
                ProviderInventoryEntry(
                    provider_id=name,
                    display_name=name,
                    kind=(
                        str(raw_provider.get("kind", "unknown"))
                        if isinstance(raw_provider, dict)
                        else "unknown"
                    ),
                    origin=origin,
                    source=source,
                    configuration_state="invalid",
                    error="Provider configuration is invalid. Reconfigure this provider.",
                    families=(),
                    surfaces=(),
                    default_for=(),
                    default_models={},
                    cli=None,
                    profile=None,
                    model_provider=None,
                    capabilities=_unknown_capabilities(),
                    connection_state=ConnectionState.MISCONFIGURED,
                    connection_detail=(
                        "This provider's configuration could not be parsed on this host."
                    ),
                )
            )
            continue
        connection = provider_connection_state(provider, harness_readiness=harness_readiness)
        surfaces = tuple(sorted(provider_families(provider)))
        families = tuple(surface for surface in surfaces if surface != "pi")
        default_models = {
            family: model
            for family in families
            if (model := provider.family_default_model(family)) is not None
        }
        inventory.append(
            ProviderInventoryEntry(
                provider_id=provider.name,
                display_name=provider.display_name or provider.name,
                kind=provider.kind,
                origin=origin,
                source=source,
                configuration_state="valid",
                error=None,
                families=families,
                surfaces=surfaces,
                default_for=tuple(sorted(provider.default_families)),
                default_models=default_models,
                cli=provider.cli,
                profile=provider.profile,
                model_provider=provider.model_provider,
                capabilities=provider_capabilities(provider),
                connection_state=connection.state,
                connection_detail=connection.detail,
            )
        )
    return inventory


__all__ = [
    "CapabilitySupport",
    "ConnectionState",
    "ProviderCapabilities",
    "ProviderConnection",
    "ProviderInventoryEntry",
    "build_provider_inventory",
    "provider_capabilities",
    "provider_connection_state",
]
