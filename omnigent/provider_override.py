"""Per-session provider-pin validation, shared by the server and runner paths.

A provider pin names a key in the host's ``providers:`` config block. It
crosses a spawn boundary the same way a model override does — it is persisted
on the session row, sent to the runner, and resolved at launch — so the value
is kept strictly data-shaped here before it is stored.

An unknown name is deliberately NOT an error at this layer: the config lives on
the host, not the server, and a name that is valid on one host may not exist on
another. Resolution happens at launch, where a missing provider falls back to
the configured default and says so, rather than failing a create the user could
not have known was wrong.
"""

from __future__ import annotations

import re

# Real provider names are short config keys ("codex", "codex-work",
# "databricks_gateway"); the bound is generous but keeps the column small.
PROVIDER_OVERRIDE_MAX_LEN = 128

# First char alphanumeric so the value can never read as a CLI flag, and the
# tail limited to what a YAML mapping key realistically holds. Deliberately
# narrower than the model charset: a provider name indexes a config dict, so it
# needs no dots, slashes, colons or brackets.
_PROVIDER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_provider_override(value: str) -> str:
    """Validate a caller-supplied provider pin and return it stripped.

    :param value: The provider name from the request, e.g. ``"codex-work"``.
    :returns: The stripped name.
    :raises ValueError: When the value is empty, too long, or contains
        anything outside the provider-name charset.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("provider override must not be empty")
    if len(stripped) > PROVIDER_OVERRIDE_MAX_LEN:
        raise ValueError(
            f"provider override must be at most {PROVIDER_OVERRIDE_MAX_LEN} characters"
        )
    if not _PROVIDER_NAME_RE.match(stripped):
        raise ValueError(
            "provider override must start with a letter or digit and contain only "
            "letters, digits, '.', '_' or '-'"
        )
    return stripped


__all__ = ["PROVIDER_OVERRIDE_MAX_LEN", "validate_provider_override"]
