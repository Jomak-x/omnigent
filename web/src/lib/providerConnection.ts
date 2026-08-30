/**
 * Explicit connection states for provider status surfaces.
 *
 * The rule this file exists to enforce: a provider surface always renders one
 * named state. A host reports a settled state per provider row
 * (`connected` / `authentication_required` / `misconfigured` / `unavailable` /
 * `unknown`); the states a *request* can be in — still connecting, timed out,
 * host unreachable, failed — are derived here from the query instead of being
 * left as an endless spinner.
 */
import type { ProviderConnectionState, ProviderInventoryEntry } from "@/hooks/useHosts";

/** The state of the inventory request itself, for the section header. */
export type ProviderFetchState = "connecting" | "ready" | "timeout" | "unavailable" | "error";

export interface ProviderFetchStatus {
  state: ProviderFetchState;
  /** A sentence to show under the state; empty when there is nothing to add. */
  detail: string;
}

/** An error carrying the HTTP status the request failed with. */
interface StatusCarryingError {
  status: number;
  message: string;
}

function statusOf(error: unknown): StatusCarryingError | null {
  if (error && typeof error === "object" && "status" in error) {
    const status = (error as { status: unknown }).status;
    if (typeof status === "number") {
      return { status, message: error instanceof Error ? error.message : String(status) };
    }
  }
  return null;
}

/**
 * Classify an inventory query into an explicit state.
 *
 * `pending` is only "connecting" while a request is actually in flight —
 * a disabled query (no host selected) is not, so it never renders as a
 * request that will never settle.
 */
export function providerFetchState(query: {
  isFetching: boolean;
  isPending: boolean;
  error: unknown;
}): ProviderFetchStatus {
  if (query.error) {
    const carried = statusOf(query.error);
    const message = query.error instanceof Error ? query.error.message : "Unknown error";
    if (carried?.status === 504) {
      return {
        state: "timeout",
        detail: "The host did not answer in time. It may be busy or half-connected.",
      };
    }
    if (carried && [409, 502, 503].includes(carried.status)) {
      return {
        state: "unavailable",
        detail: "The host is not reachable right now. Providers are listed once it reconnects.",
      };
    }
    return { state: "error", detail: message };
  }
  if (query.isPending || query.isFetching) return { state: "connecting", detail: "" };
  return { state: "ready", detail: "" };
}

/** The settled state of one row, defaulting an older host's silence to unknown. */
export function providerConnectionState(
  provider: Pick<ProviderInventoryEntry, "connection_state">,
): ProviderConnectionState {
  return provider.connection_state ?? "unknown";
}

export type ProviderStateTone = "ok" | "warning" | "error" | "muted";

export interface ProviderStatePresentation {
  label: string;
  tone: ProviderStateTone;
  /** Whether the user can do something about it right now. */
  actionable: boolean;
}

const PRESENTATION: Record<ProviderConnectionState, ProviderStatePresentation> = {
  connected: { label: "Connected", tone: "ok", actionable: false },
  authentication_required: {
    label: "Authentication required",
    tone: "warning",
    actionable: true,
  },
  misconfigured: { label: "Misconfigured", tone: "error", actionable: true },
  unavailable: { label: "Unavailable", tone: "error", actionable: true },
  unknown: { label: "Unknown", tone: "muted", actionable: false },
};

/** How to render a settled row state. */
export function providerStatePresentation(
  state: ProviderConnectionState,
): ProviderStatePresentation {
  return PRESENTATION[state] ?? PRESENTATION.unknown;
}

const FETCH_LABEL: Record<ProviderFetchState, string> = {
  connecting: "Connecting…",
  ready: "",
  timeout: "Timed out",
  unavailable: "Host unavailable",
  error: "Couldn't load providers",
};

/** The header label for a fetch state; empty once the list is showing. */
export function providerFetchLabel(state: ProviderFetchState): string {
  return FETCH_LABEL[state] ?? FETCH_LABEL.error;
}
