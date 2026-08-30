// Tests for the Providers settings section — the read-only provider inventory
// (per host) that reuses Omni Setup's detection. Covers row rendering with
// honest status, capability chips, the host picker, error/empty/loading
// states, and the Manage affordance that reuses the harness setup dialog.

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import type * as AgentLabelsModule from "@/lib/agentLabels";
import type { Host, ProviderInventoryEntry, ProviderUsage } from "@/hooks/useHosts";

const mocks = vi.hoisted(() => ({
  hostsLoading: false,
  hosts: [] as Host[],
  inventoryHostId: undefined as string | null | undefined,
  inventoryEnabled: undefined as boolean | undefined,
  inventoryLoading: false,
  inventoryError: false,
  inventoryErrorObj: null as Error | null,
  providers: [] as ProviderInventoryEntry[],
  refetch: vi.fn(),
  usage: null as ProviderUsage | null,
  usagePending: false,
  usageError: false,
  refreshUsage: vi.fn(),
  setupSteps: {} as Record<string, unknown[]>,
  lastSetupProps: null as { harness: string | null; host: Host | null | undefined } | null,
}));

vi.mock("@/lib/CapabilitiesContext", () => ({
  useServerInfo: () => ({
    accounts_enabled: false,
    login_url: null,
    single_user: false,
  }),
}));
vi.mock("@/hooks/useHosts", () => ({
  useHosts: () => ({ data: mocks.hosts, isLoading: mocks.hostsLoading }),
  useProviderInventory: (hostId: string | null | undefined, enabled: boolean) => {
    mocks.inventoryHostId = hostId;
    mocks.inventoryEnabled = enabled;
    return {
      data: mocks.providers,
      isLoading: mocks.inventoryLoading,
      isPending: mocks.inventoryLoading,
      isError: mocks.inventoryError,
      error: mocks.inventoryErrorObj,
      isFetching: mocks.inventoryLoading,
      refetch: mocks.refetch,
    };
  },
  useProviderUsage: () => ({
    data: mocks.usage,
    isPending: mocks.usagePending,
    isError: mocks.usageError,
  }),
  useRefreshProviderUsage: () => ({
    mutate: mocks.refreshUsage,
    isPending: false,
  }),
}));
vi.mock("@/lib/agentLabels", async (importOriginal) => {
  const original = await importOriginal<typeof AgentLabelsModule>();
  return {
    ...original,
    useHarnessSetupSteps: () => mocks.setupSteps,
  };
});
vi.mock("@/shell/HarnessSetupDialog", () => ({
  HarnessSetupDialog: (props: {
    open: boolean;
    harness: string | null;
    host: Host | null | undefined;
  }) => {
    if (props.open) mocks.lastSetupProps = { harness: props.harness, host: props.host };
    return props.open ? (
      <div data-testid="harness-setup-stub">{`${props.harness}@${props.host?.host_id ?? ""}`}</div>
    ) : null;
  },
}));
// Radix Select portals + pointer events can't be driven in jsdom; stub to a
// native <select> (lifts the trigger's data-testid), same as SettingsPage.test.
vi.mock("@/components/ui/select", async () => {
  const { Children, isValidElement } = await import("react");
  const SelectTrigger = ({ children }: { children?: ReactNode }) => children;
  const Select = ({
    value,
    onValueChange,
    children,
  }: {
    value: string;
    onValueChange: (v: string) => void;
    children: ReactNode;
  }) => {
    const kids = Children.toArray(children);
    const trigger = kids.find((c) => isValidElement(c) && c.type === SelectTrigger);
    const testId =
      isValidElement(trigger) && trigger.props && typeof trigger.props === "object"
        ? (trigger.props as Record<string, unknown>)["data-testid"]
        : undefined;
    return (
      <select
        data-testid={typeof testId === "string" ? testId : undefined}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
      >
        {kids.filter((c) => !(isValidElement(c) && c.type === SelectTrigger))}
      </select>
    );
  };
  return {
    Select,
    SelectTrigger,
    SelectValue: () => null,
    SelectContent: ({ children }: { children: ReactNode }) => children,
    SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
      <option value={value}>{children}</option>
    ),
  };
});

import { SettingsPage } from "./SettingsPage";

function host(id: string, name: string): Host {
  return {
    host_id: id,
    name,
    owner: "jakob",
    status: "online",
  };
}

function provider(partial: Partial<ProviderInventoryEntry>): ProviderInventoryEntry {
  return {
    id: "prov",
    display_name: "Prov",
    kind: "subscription",
    origin: "configured",
    source: "config",
    configuration_state: "valid",
    error: null,
    families: [],
    surfaces: [],
    default_for: [],
    default_models: {},
    cli: null,
    profile: null,
    model_provider: null,
    capabilities: {
      model_discovery: "supported",
      usage_status: "unsupported",
      multiple_profiles: "unknown",
      interactive_cli: "supported",
    },
    connection_state: "connected",
    connection_detail: "The codex CLI is installed and reports a usable credential.",
    ...partial,
  };
}

/** Mirrors the status-carrying error `useProviderInventory` throws. */
function httpError(status: number, message: string): Error {
  return Object.assign(new Error(message), { status });
}

function renderPage(path = "/settings/providers") {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={[path]}>
        <SettingsPage />
      </MemoryRouter>
    </TooltipProvider>,
  );
}

beforeEach(() => {
  mocks.hostsLoading = false;
  mocks.hosts = [host("host_1", "MacBook")];
  mocks.inventoryLoading = false;
  mocks.inventoryError = false;
  mocks.inventoryErrorObj = null;
  mocks.providers = [];
  mocks.refetch.mockReset();
  mocks.usage = null;
  mocks.usagePending = false;
  mocks.usageError = false;
  mocks.refreshUsage.mockReset();
  mocks.setupSteps = {};
  mocks.lastSetupProps = null;
});
afterEach(cleanup);

describe("ProvidersSection", () => {
  it("renders provider rows with honest status and metadata", () => {
    mocks.providers = [
      provider({
        id: "codex",
        display_name: "Codex",
        cli: "codex",
        families: ["openai"],
        default_models: { openai: "gpt-5.4" },
      }),
      provider({
        id: "broken",
        display_name: "Broken Gateway",
        kind: "gateway",
        origin: "detected",
        configuration_state: "invalid",
        error: "Provider configuration is invalid. Reconfigure this provider.",
        connection_state: "misconfigured",
        connection_detail: "This provider's configuration could not be parsed on this host.",
        capabilities: {
          model_discovery: "unknown",
          usage_status: "unknown",
          multiple_profiles: "unknown",
          interactive_cli: "unsupported",
        },
      }),
    ];
    renderPage();

    const codex = screen.getByTestId("provider-row-codex");
    expect(within(codex).getByText("Codex")).toBeInTheDocument();
    expect(within(codex).getByText("Connected")).toBeInTheDocument();
    expect(
      within(codex).getByText("The codex CLI is installed and reports a usable credential."),
    ).toBeInTheDocument();
    expect(within(codex).getByText(/Families: openai \(gpt-5\.4\)/)).toBeInTheDocument();
    expect(within(codex).getByText("CLI: codex")).toBeInTheDocument();
    expect(within(codex).queryByText("Detected")).toBeNull();

    const broken = screen.getByTestId("provider-row-broken");
    expect(within(broken).getByText("Misconfigured")).toBeInTheDocument();
    expect(screen.getByTestId("provider-state-broken")).toHaveAttribute(
      "data-state",
      "misconfigured",
    );
    expect(
      within(broken).getByText("Provider configuration is invalid. Reconfigure this provider."),
    ).toBeInTheDocument();
    expect(within(broken).getByText("Detected")).toBeInTheDocument();
  });

  it("renders capability chips with per-state indication", () => {
    mocks.providers = [provider({ id: "codex", display_name: "Codex" })];
    renderPage();

    expect(screen.getByTestId("provider-capability-model-discovery")).toHaveTextContent(
      "Model discovery",
    );
    expect(screen.getByTestId("provider-capability-usage-status")).toHaveTextContent(
      "Usage status",
    );
    expect(screen.getByTestId("provider-capability-multiple-profiles")).toHaveTextContent(
      "Multiple profiles (?)",
    );
    expect(screen.getByTestId("provider-capability-interactive-cli")).toHaveTextContent(
      "Interactive CLI",
    );
  });

  it("shows the empty state when the host reports no providers", () => {
    renderPage();
    expect(screen.getByTestId("provider-empty")).toHaveTextContent(/No providers/);
  });

  it("shows a retryable error instead of an indefinite spinner", () => {
    mocks.inventoryError = true;
    mocks.inventoryErrorObj = new Error("host unreachable");
    renderPage();

    expect(screen.getByTestId("provider-error")).toHaveTextContent("host unreachable");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
  });

  it("offers Manage only for CLI providers the setup catalog knows", () => {
    mocks.setupSteps = { codex: [] };
    mocks.providers = [
      provider({ id: "codex", display_name: "Codex", cli: "codex" }),
      provider({ id: "gateway", display_name: "Work Gateway", kind: "gateway" }),
      provider({ id: "mystery", display_name: "Mystery CLI", cli: "unknown-cli" }),
    ];
    renderPage();

    expect(screen.getByTestId("provider-manage-codex")).toBeInTheDocument();
    expect(screen.queryByTestId("provider-manage-gateway")).toBeNull();
    expect(screen.queryByTestId("provider-manage-mystery")).toBeNull();

    fireEvent.click(screen.getByTestId("provider-manage-codex"));
    expect(screen.getByTestId("harness-setup-stub")).toHaveTextContent("codex@host_1");
  });

  it("switches hosts through the picker when several are connected", () => {
    mocks.hosts = [host("host_1", "MacBook"), host("host_2", "Studio")];
    renderPage();

    // Single-host label is replaced by the picker; inventory targets host_1.
    expect(screen.queryByText("Host: MacBook")).toBeNull();
    expect(mocks.inventoryHostId).toBe("host_1");

    const picker = screen.getByTestId("provider-host-select") as HTMLSelectElement;
    expect(picker.value).toBe("host_1");
    fireEvent.change(picker, { target: { value: "host_2" } });
    expect(mocks.inventoryHostId).toBe("host_2");
  });

  it("explains what to do when no host is connected", () => {
    mocks.hosts = [];
    renderPage();
    expect(screen.getByText(/No host is connected yet/)).toBeInTheDocument();
  });

  it("renders an actionable state instead of a bare validity flag", () => {
    mocks.providers = [
      provider({
        id: "claude",
        display_name: "Claude",
        cli: "claude",
        connection_state: "authentication_required",
        connection_detail: "The claude CLI is installed but has no credential yet.",
      }),
    ];
    renderPage();

    const row = screen.getByTestId("provider-row-claude");
    expect(within(row).getByText("Authentication required")).toBeInTheDocument();
    expect(
      within(row).getByText("The claude CLI is installed but has no credential yet."),
    ).toBeInTheDocument();
  });

  it("says unknown, not connected, for a host that reports no state", () => {
    // A host predating connection states omits the field entirely.
    const row = provider({ id: "legacy", display_name: "Legacy" });
    delete row.connection_state;
    delete row.connection_detail;
    mocks.providers = [row];
    renderPage();

    expect(screen.getByTestId("provider-state-legacy")).toHaveAttribute("data-state", "unknown");
    expect(within(screen.getByTestId("provider-row-legacy")).getByText("Unknown")).toBeVisible();
  });

  it("names a host timeout rather than reporting a generic failure", () => {
    mocks.inventoryError = true;
    mocks.inventoryErrorObj = httpError(504, "504 Gateway Timeout");
    renderPage();

    const block = screen.getByTestId("provider-error");
    expect(block).toHaveAttribute("data-state", "timeout");
    expect(block).toHaveTextContent("Timed out");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
  });

  it("names an offline host as unavailable", () => {
    mocks.inventoryError = true;
    mocks.inventoryErrorObj = httpError(409, "409 Conflict");
    renderPage();

    const block = screen.getByTestId("provider-error");
    expect(block).toHaveAttribute("data-state", "unavailable");
    expect(block).toHaveTextContent("Host unavailable");
  });

  const CODEX_CAPABILITIES = {
    model_discovery: "supported",
    usage_status: "supported",
    multiple_profiles: "unsupported",
    interactive_cli: "supported",
  } as const;

  function codexRow(): ProviderInventoryEntry {
    return provider({
      id: "codex",
      display_name: "Codex",
      cli: "codex",
      capabilities: CODEX_CAPABILITIES,
    });
  }

  function usageStatus(partial: Partial<ProviderUsage> = {}): ProviderUsage {
    return {
      provider_id: "codex",
      profile: null,
      state: "exhausted",
      windows: [],
      plan: "plus",
      message: null,
      checked_at: Date.now() / 1000,
      ...partial,
    };
  }

  it("draws each reported quota window, binding limit first", () => {
    mocks.providers = [codexRow()];
    mocks.usage = usageStatus({
      windows: [
        {
          id: "secondary",
          label: "Weekly limit",
          used_percent: 47,
          window_minutes: 10080,
          resets_at: Date.now() / 1000 + 3 * 86400,
        },
        {
          id: "primary",
          label: "5-hour limit",
          used_percent: 100,
          window_minutes: 300,
          resets_at: Date.now() / 1000 + 2 * 3600,
        },
      ],
    });
    renderPage();

    const block = screen.getByTestId("provider-usage-codex");
    expect(block).toHaveAttribute("data-state", "exhausted");
    expect(within(block).getByText("Exhausted")).toBeInTheDocument();
    expect(within(block).getByText("plus")).toBeInTheDocument();
    const windows = within(block).getAllByText(/limit$/);
    expect(windows.map((node) => node.textContent)).toEqual(["5-hour limit", "Weekly limit"]);
    expect(within(block).getByText("100% used · resets in 2 hours")).toBeInTheDocument();
    expect(within(block).getByText("47% used · resets in 3 days")).toBeInTheDocument();
  });

  it("says nothing was reported rather than drawing an empty meter", () => {
    mocks.providers = [codexRow()];
    mocks.usage = usageStatus({
      state: "unknown",
      windows: [],
      message: "This version of the codex CLI does not report usage limits.",
    });
    renderPage();

    const block = screen.getByTestId("provider-usage-codex");
    expect(within(block).getByText("Not reported")).toBeInTheDocument();
    expect(
      within(block).getByText("This version of the codex CLI does not report usage limits."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("provider-usage-window-codex-primary")).toBeNull();
  });

  it("re-probes only when asked", () => {
    mocks.providers = [codexRow()];
    mocks.usage = usageStatus({ state: "available" });
    renderPage();

    expect(mocks.refreshUsage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("provider-usage-refresh-codex"));
    expect(mocks.refreshUsage).toHaveBeenCalledTimes(1);
  });

  it("omits usage entirely for a provider that cannot report it", () => {
    mocks.providers = [provider({ id: "work", display_name: "Work", kind: "gateway" })];
    mocks.usage = usageStatus();
    renderPage();

    expect(screen.queryByTestId("provider-usage-work")).toBeNull();
  });

  it("shows loading states for hosts and inventory", () => {
    mocks.hostsLoading = true;
    const { unmount } = renderPage();
    expect(screen.getByText("Loading hosts…")).toBeInTheDocument();

    unmount();
    cleanup();
    mocks.hostsLoading = false;
    mocks.inventoryLoading = true;
    renderPage();
    expect(screen.getByTestId("provider-loading")).toBeInTheDocument();
  });
});
