import { describe, expect, it } from "vitest";
import {
  providerConnectionState,
  providerFetchLabel,
  providerFetchState,
  providerStatePresentation,
} from "./providerConnection";
import type { ProviderInventoryEntry } from "@/hooks/useHosts";

function httpError(status: number): Error {
  return Object.assign(new Error(`${status} failed`), { status });
}

describe("providerFetchState", () => {
  it("reports connecting only while a request is in flight", () => {
    expect(providerFetchState({ isPending: true, isFetching: true, error: null }).state).toBe(
      "connecting",
    );
    expect(providerFetchState({ isPending: false, isFetching: false, error: null }).state).toBe(
      "ready",
    );
  });

  it("separates a host timeout from a generic failure", () => {
    const timedOut = providerFetchState({
      isPending: false,
      isFetching: false,
      error: httpError(504),
    });
    expect(timedOut.state).toBe("timeout");
    expect(timedOut.detail).toContain("did not answer in time");
  });

  it("treats an offline or dropped host as unavailable, not an error", () => {
    for (const status of [409, 502, 503]) {
      expect(
        providerFetchState({ isPending: false, isFetching: false, error: httpError(status) }).state,
      ).toBe("unavailable");
    }
  });

  it("falls back to error with the message for anything else", () => {
    const failed = providerFetchState({
      isPending: false,
      isFetching: false,
      error: new Error("boom"),
    });
    expect(failed.state).toBe("error");
    expect(failed.detail).toBe("boom");
  });

  it("prefers the error over a refetch that is still in flight", () => {
    // A background refetch must not hide a failure behind a spinner.
    expect(
      providerFetchState({ isPending: false, isFetching: true, error: httpError(504) }).state,
    ).toBe("timeout");
  });
});

describe("providerConnectionState", () => {
  it("defaults a host that reports nothing to unknown", () => {
    expect(providerConnectionState({} as ProviderInventoryEntry)).toBe("unknown");
    expect(providerConnectionState({ connection_state: "connected" })).toBe("connected");
  });

  it("marks the states a user can act on", () => {
    expect(providerStatePresentation("authentication_required").actionable).toBe(true);
    expect(providerStatePresentation("misconfigured").actionable).toBe(true);
    expect(providerStatePresentation("connected").actionable).toBe(false);
    expect(providerStatePresentation("unknown").tone).toBe("muted");
  });

  it("never labels a settled state with an empty string", () => {
    for (const state of [
      "connected",
      "authentication_required",
      "misconfigured",
      "unavailable",
      "unknown",
    ] as const) {
      expect(providerStatePresentation(state).label).not.toBe("");
    }
  });

  it("labels every non-ready fetch state", () => {
    for (const state of ["connecting", "timeout", "unavailable", "error"] as const) {
      expect(providerFetchLabel(state)).not.toBe("");
    }
    expect(providerFetchLabel("ready")).toBe("");
  });
});
