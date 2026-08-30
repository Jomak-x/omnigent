// Tests for the pre-session provider status shown in the "Configure …" modal:
// which provider serves the agent, whether it is usable, and how its quota is
// surfaced without letting the modal start a probe on open.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Host, ProviderInventoryEntry, ProviderUsage } from "@/hooks/useHosts";

const mocks = vi.hoisted(() => ({
  providers: [] as ProviderInventoryEntry[],
  inventoryEnabled: undefined as boolean | undefined,
  usage: null as ProviderUsage | null,
  usageEnabled: undefined as boolean | undefined,
  refreshUsage: vi.fn(),
}));

vi.mock("@/hooks/useHosts", () => ({
  useProviderInventory: (_hostId: string | null | undefined, enabled: boolean) => {
    mocks.inventoryEnabled = enabled;
    return { data: mocks.providers };
  },
  useProviderUsage: (
    _hostId: string | null | undefined,
    _providerId: string | null | undefined,
    enabled: boolean,
  ) => {
    mocks.usageEnabled = enabled;
    return { data: mocks.usage };
  },
  useRefreshProviderUsage: () => ({ mutate: mocks.refreshUsage, isPending: false }),
}));

const { NewChatProviderStatus, providerForHarness } = await import("./NewChatProviderStatus");

function providerRow(partial: Partial<ProviderInventoryEntry> = {}): ProviderInventoryEntry {
  return {
    id: "codex",
    display_name: "Codex",
    kind: "subscription",
    origin: "configured",
    source: "config",
    configuration_state: "valid",
    error: null,
    families: ["openai"],
    surfaces: ["openai"],
    default_for: ["openai"],
    default_models: {},
    cli: "codex",
    profile: null,
    model_provider: null,
    capabilities: {
      model_discovery: "supported",
      usage_status: "supported",
      multiple_profiles: "unsupported",
      interactive_cli: "supported",
    },
    default_for_harnesses: ["codex-native"],
    connection_state: "connected",
    connection_detail: "The codex CLI is installed and reports a usable credential.",
    ...partial,
  };
}

const HOST = { host_id: "host_1", name: "MacBook" } as Host;

beforeEach(() => {
  mocks.providers = [];
  mocks.usage = null;
  mocks.inventoryEnabled = undefined;
  mocks.usageEnabled = undefined;
  mocks.refreshUsage.mockReset();
});
afterEach(cleanup);

describe("providerForHarness", () => {
  it("uses the host's own harness mapping rather than guessing from families", () => {
    const rows = [
      providerRow({ id: "work", display_name: "Work", default_for_harnesses: ["pi-native"] }),
      providerRow(),
    ];

    expect(providerForHarness(rows, "codex-native")?.id).toBe("codex");
    expect(providerForHarness(rows, "pi-native")?.id).toBe("work");
    expect(providerForHarness(rows, "claude-native")).toBeNull();
  });

  it("treats a host that reports no mapping as no answer, not a wrong one", () => {
    const legacy = providerRow();
    delete legacy.default_for_harnesses;

    expect(providerForHarness([legacy], "codex-native")).toBeNull();
    expect(providerForHarness(undefined, "codex-native")).toBeNull();
    expect(providerForHarness([providerRow()], null)).toBeNull();
  });
});

describe("NewChatProviderStatus", () => {
  it("names the provider that will serve the agent", () => {
    mocks.providers = [providerRow()];
    render(<NewChatProviderStatus host={HOST} harness="codex-native" open />);

    const block = screen.getByTestId("new-chat-provider-status");
    expect(block).toHaveAttribute("data-state", "connected");
    expect(block).toHaveTextContent("Codex");
    expect(block).toHaveTextContent("Connected");
  });

  it("explains an unusable provider before the session is started", () => {
    mocks.providers = [
      providerRow({
        connection_state: "authentication_required",
        connection_detail: "The codex CLI is installed but has no credential yet.",
      }),
    ];
    render(<NewChatProviderStatus host={HOST} harness="codex-native" open />);

    const block = screen.getByTestId("new-chat-provider-status");
    expect(block).toHaveAttribute("data-state", "authentication_required");
    expect(block).toHaveTextContent("The codex CLI is installed but has no credential yet.");
  });

  it("renders nothing when the host names no provider for the harness", () => {
    mocks.providers = [providerRow()];
    render(<NewChatProviderStatus host={HOST} harness="claude-native" open />);

    expect(screen.queryByTestId("new-chat-provider-status")).toBeNull();
  });

  it("renders nothing for a sandbox session with no host", () => {
    mocks.providers = [providerRow()];
    render(<NewChatProviderStatus host={null} harness="codex-native" open />);

    expect(screen.queryByTestId("new-chat-provider-status")).toBeNull();
  });

  it("never lets opening the modal start a usage probe", () => {
    mocks.providers = [providerRow()];
    render(<NewChatProviderStatus host={HOST} harness="codex-native" open />);

    // The inventory is a cheap config read, so it may fetch; the usage probe
    // can start a vendor CLI, so it must stay disabled until asked.
    expect(mocks.inventoryEnabled).toBe(true);
    expect(mocks.usageEnabled).toBe(false);
    expect(screen.getByTestId("new-chat-provider-usage-check")).toBeInTheDocument();
    expect(mocks.refreshUsage).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("new-chat-provider-usage-check"));
    expect(mocks.refreshUsage).toHaveBeenCalledTimes(1);
  });

  it("shows a quota the host already read, with its age", () => {
    mocks.providers = [providerRow()];
    mocks.usage = {
      provider_id: "codex",
      profile: null,
      state: "exhausted",
      windows: [
        {
          id: "primary",
          label: "5-hour limit",
          used_percent: 100,
          window_minutes: 300,
          resets_at: Date.now() / 1000 + 3600,
        },
      ],
      plan: "plus",
      message: null,
      checked_at: Date.now() / 1000 - 300,
    };
    render(<NewChatProviderStatus host={HOST} harness="codex-native" open />);

    const usage = screen.getByTestId("new-chat-provider-usage");
    expect(usage).toHaveAttribute("data-state", "exhausted");
    expect(usage).toHaveTextContent("Exhausted");
    expect(screen.getByTestId("new-chat-provider-window-primary")).toHaveTextContent(
      "5-hour limit: 100% used · resets in 1 hour",
    );
    expect(usage).toHaveTextContent("checked 5 minutes ago");
  });

  it("says a quota was not reported instead of drawing nothing", () => {
    mocks.providers = [providerRow()];
    mocks.usage = {
      provider_id: "codex",
      profile: null,
      state: "unknown",
      windows: [],
      plan: null,
      message: "This version of the codex CLI does not report usage limits.",
      checked_at: Date.now() / 1000,
    };
    render(<NewChatProviderStatus host={HOST} harness="codex-native" open />);

    const usage = screen.getByTestId("new-chat-provider-usage");
    expect(usage).toHaveTextContent("Not reported");
    expect(usage).toHaveTextContent("This version of the codex CLI does not report usage limits.");
  });

  it("omits the quota affordance for a provider that cannot report one", () => {
    mocks.providers = [
      providerRow({
        capabilities: {
          model_discovery: "supported",
          usage_status: "unsupported",
          multiple_profiles: "unsupported",
          interactive_cli: "supported",
        },
      }),
    ];
    render(<NewChatProviderStatus host={HOST} harness="codex-native" open />);

    expect(screen.queryByTestId("new-chat-provider-usage-check")).toBeNull();
  });
});
