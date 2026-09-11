import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ProviderSettingsSection } from "./ProviderSettingsSection";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import { useHosts, type Host } from "@/hooks/useHosts";
import {
  detectSetup,
  fetchSetupInventory,
  runSetupAction,
  startSetupOperation,
  type SetupInventory,
} from "@/lib/providerSetupApi";

vi.mock("@/hooks/useHosts", () => ({ useHosts: vi.fn() }));
vi.mock("@/lib/providerSetupApi", () => ({
  detectSetup: vi.fn(),
  fetchSetupInventory: vi.fn(),
  runSetupAction: vi.fn(),
  startSetupOperation: vi.fn(),
}));
vi.mock("@/components/ProviderSetupTerminal", () => ({
  ProviderSetupTerminal: () => <div data-testid="setup-terminal" />,
}));
vi.mock("@/shell/HarnessSetupDialog", () => ({
  HarnessSetupDialog: () => null,
}));
// Radix Select uses portals and pointer events that are incidental to these
// host-scoping tests. A native select keeps each option and payload path easy
// to exercise in jsdom.
vi.mock("@/components/ui/select", () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value?: string;
    onValueChange: (next: string) => void;
    children: ReactNode;
  }) => (
    <select
      data-testid="mock-select"
      value={value ?? ""}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => children,
  SelectItem: ({
    value,
    disabled,
    children,
  }: {
    value: string;
    disabled?: boolean;
    children: ReactNode;
  }) => (
    <option value={value} disabled={disabled}>
      {children}
    </option>
  ),
}));

const useHostsMock = vi.mocked(useHosts);
const fetchInventoryMock = vi.mocked(fetchSetupInventory);
const detectSetupMock = vi.mocked(detectSetup);
const runSetupActionMock = vi.mocked(runSetupAction);
const startSetupOperationMock = vi.mocked(startSetupOperation);

const online = (host_id: string, name = host_id): Host => ({
  host_id,
  name,
  owner: "jakob@example.com",
  status: "online",
});

const offline = (host_id: string, name = host_id): Host => ({
  ...online(host_id, name),
  status: "offline",
});

function inventory(overrides: Partial<SetupInventory> = {}): SetupInventory {
  return {
    feature_enabled: true,
    mutations_enabled: true,
    providers: [],
    key_providers: [{ id: "openai", label: "OpenAI", family: "openai", base_url: "" }],
    acp_agents: [],
    harness_settings: {
      cursor_key_configured: false,
      antigravity_key_configured: false,
      copilot_key_configured: false,
    },
    dismissed_detections: [],
    effective_defaults: {},
    ...overrides,
  };
}

function enabledInfo(enabled = true) {
  return { ...FALLBACK_SERVER_INFO, features: { harness_install: enabled } };
}

function renderSection(featureEnabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <CapabilitiesProvider info={enabledInfo(featureEnabled)}>
        <ProviderSettingsSection />
      </CapabilitiesProvider>
    </QueryClientProvider>,
  );
  return { ...view, client };
}

function hostSelect(): HTMLSelectElement {
  return screen.getAllByTestId("mock-select")[0] as HTMLSelectElement;
}

function actionResult(hostId: string, message = "Saved") {
  return { ok: true, message, inventory: inventories.get(hostId) ?? inventory() };
}

let hosts: Host[] | undefined;
let inventories: Map<string, SetupInventory>;

beforeEach(() => {
  localStorage.clear();
  hosts = [];
  inventories = new Map();
  useHostsMock.mockReset();
  fetchInventoryMock.mockReset();
  detectSetupMock.mockReset();
  runSetupActionMock.mockReset();
  startSetupOperationMock.mockReset();
  useHostsMock.mockImplementation(
    () =>
      ({
        data: hosts,
        isPending: false,
        isError: false,
        refetch: vi.fn(),
      }) as unknown as ReturnType<typeof useHosts>,
  );
  fetchInventoryMock.mockImplementation(async (hostId) => inventories.get(hostId) ?? inventory());
  detectSetupMock.mockResolvedValue({ providers: [], imports: [], models: {} });
  runSetupActionMock.mockImplementation(async (hostId) => actionResult(hostId));
  startSetupOperationMock.mockResolvedValue({
    operation_id: "op-1",
    state: "running",
    action: "codex-login",
    exit_code: null,
    error: null,
  });
});

afterEach(() => cleanup());

describe("ProviderSettingsSection", () => {
  it("selects the sole online computer and renders its inventory", async () => {
    hosts = [online("mac", "Jakob's Mac")];
    inventories.set(
      "mac",
      inventory({
        providers: [
          {
            name: "work-openai",
            kind: "api_key",
            families: ["openai"],
            defaults: ["openai"],
            default_scopes: ["openai"],
            credential_sources: { openai: "keychain" },
            models: { openai: "gpt-5.6" },
            base_urls: {},
          },
        ],
        effective_defaults: { openai: "work-openai" },
      }),
    );

    renderSection();

    expect(await screen.findByText("work-openai")).toBeInTheDocument();
    expect(fetchInventoryMock).toHaveBeenCalledWith("mac", expect.any(AbortSignal));
    expect(hostSelect().value).toBe("mac");
    expect(screen.getByText(/gpt-5\.6/)).toBeInTheDocument();
  });

  it("requires an explicit selection with several computers, but restores a remembered one", async () => {
    hosts = [online("mac", "Mac"), online("linux", "Linux")];
    inventories.set("linux", inventory());
    renderSection();

    expect(screen.getByText(/Choose a computer\. Omnigent will never move/)).toBeInTheDocument();
    expect(fetchInventoryMock).not.toHaveBeenCalled();

    fireEvent.change(hostSelect(), { target: { value: "linux" } });
    await waitFor(() =>
      expect(fetchInventoryMock).toHaveBeenCalledWith("linux", expect.any(AbortSignal)),
    );
    expect(localStorage.getItem("omnigent:provider-settings-host")).toBe("linux");

    cleanup();
    fetchInventoryMock.mockClear();
    localStorage.setItem("omnigent:provider-settings-host", "linux");
    localStorage.setItem("omnigent:provider-settings-host:name", "Linux");
    renderSection();
    await waitFor(() =>
      expect(fetchInventoryMock).toHaveBeenCalledWith("linux", expect.any(AbortSignal)),
    );
  });

  it("does not retarget a missing remembered computer", async () => {
    localStorage.setItem("omnigent:provider-settings-host", "gone");
    localStorage.setItem("omnigent:provider-settings-host:name", "Old laptop");
    hosts = [online("mac", "Mac")];
    renderSection();

    expect(await screen.findByText(/Old laptop is unavailable/)).toBeInTheDocument();
    expect(fetchInventoryMock).not.toHaveBeenCalled();
    expect(hostSelect().value).toBe("gone");
  });

  it("does not fetch setup inventory or expose mutations for an offline computer", async () => {
    hosts = [offline("mac", "Mac")];
    renderSection();

    expect(await screen.findByRole("status")).toHaveTextContent("Mac is offline");
    expect(fetchInventoryMock).not.toHaveBeenCalled();
    expect(runSetupActionMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /detect credentials/i })).toBeNull();
  });

  it("keeps the configuration overview read-only when harness install is disabled", async () => {
    hosts = [online("mac")];
    inventories.set(
      "mac",
      inventory({
        providers: [
          {
            name: "read-only-provider",
            kind: "api_key",
            families: ["openai"],
            defaults: [],
            default_scopes: ["openai"],
            credential_sources: { openai: "environment" },
            models: { openai: "gpt-5.6" },
            base_urls: {},
          },
        ],
      }),
    );
    renderSection(false);

    expect(await screen.findByText("read-only-provider")).toBeInTheDocument();
    expect(screen.getByText(/Provider setup changes are disabled/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /detect credentials|add provider|remove/i }),
    ).toBeNull();
    expect(runSetupActionMock).not.toHaveBeenCalled();
  });

  it("runs credential detection only after the explicit button click", async () => {
    hosts = [online("mac")];
    inventories.set("mac", inventory());
    renderSection();

    await screen.findByRole("button", { name: /detect credentials/i });
    expect(detectSetupMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /detect credentials/i }));
    await waitFor(() => expect(detectSetupMock).toHaveBeenCalledWith("mac", undefined));
  });

  it("preserves an ACP import path and preview fingerprints through confirmation", async () => {
    hosts = [online("mac")];
    inventories.set("mac", inventory());
    detectSetupMock.mockResolvedValue({
      providers: [],
      models: {},
      default_models: {},
      imports: [
        {
          source: "openclaw",
          name: "review-agent",
          slug: "review-agent",
          command: "review-agent (2 arguments hidden)",
          model: null,
          fingerprint: "sha256-preview",
        },
      ],
    });
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: /advanced provider tools/i }));
    fireEvent.change(screen.getByLabelText("Configuration path"), {
      target: { value: "/tmp/openclaw.json" },
    });
    fireEvent.click(screen.getByRole("button", { name: /preview import/i }));

    await waitFor(() =>
      expect(detectSetupMock).toHaveBeenCalledWith("mac", {
        import_source: "openclaw",
        import_path: "/tmp/openclaw.json",
      }),
    );
    fireEvent.click(await screen.findByRole("checkbox", { name: /review-agent/i }));
    fireEvent.click(screen.getByRole("button", { name: /import selected openclaw agents/i }));

    await waitFor(() =>
      expect(runSetupActionMock).toHaveBeenCalledWith("mac", {
        action: "import_acp",
        source: "openclaw",
        names: ["review-agent"],
        path: "/tmp/openclaw.json",
        fingerprints: { "review-agent": "sha256-preview" },
      }),
    );
  });

  it("requires a model for keys and clears then closes the secret form after acknowledgement", async () => {
    hosts = [online("mac")];
    inventories.set("mac", inventory());
    renderSection();

    await screen.findByRole("button", { name: /add provider/i });
    fireEvent.click(screen.getByRole("button", { name: /add provider/i }));
    const save = screen.getByRole("button", { name: /save provider/i });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Default model"), { target: { value: "gpt-5.6" } });
    fireEvent.change(screen.getByLabelText("API key or token"), {
      target: { value: "super-secret" },
    });
    fireEvent.click(save);

    await waitFor(() =>
      expect(runSetupActionMock).toHaveBeenCalledWith("mac", {
        action: "add_key",
        provider: "openai",
        name: undefined,
        model: "gpt-5.6",
        secret: "super-secret",
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /save provider/i })).toBeNull(),
    );

    fireEvent.click(screen.getByRole("button", { name: /add provider/i }));
    expect(screen.getByLabelText("API key or token")).toHaveValue("");
  });

  it("sends gateway families, models, selected protocol, and credential payload", async () => {
    hosts = [online("mac")];
    inventories.set("mac", inventory());
    renderSection();

    await screen.findByRole("button", { name: /add gateway/i });
    fireEvent.click(screen.getByRole("button", { name: /add gateway/i }));
    fireEvent.change(screen.getByLabelText("Gateway name"), { target: { value: "relay" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://relay.example" },
    });
    fireEvent.change(screen.getByLabelText("Anthropic model"), {
      target: { value: "claude-sonnet" },
    });
    fireEvent.change(screen.getByLabelText("OpenAI model"), { target: { value: "gpt-5.6" } });
    fireEvent.change(screen.getAllByTestId("mock-select").at(-1) as HTMLSelectElement, {
      target: { value: "chat" },
    });
    fireEvent.change(screen.getByLabelText("API key or token"), {
      target: { value: "gateway-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save gateway/i }));

    await waitFor(() =>
      expect(runSetupActionMock).toHaveBeenCalledWith("mac", {
        action: "add_gateway",
        name: "relay",
        base_url: "https://relay.example",
        families: ["anthropic", "openai"],
        wire_api: "chat",
        models: { anthropic: "claude-sonnet", openai: "gpt-5.6" },
        secret: "gateway-secret",
      }),
    );
  });

  it("sends the complete Bedrock form without exposing the saved secret afterward", async () => {
    hosts = [online("mac")];
    inventories.set("mac", inventory());
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: /add bedrock/i }));
    fireEvent.change(screen.getByLabelText("Model ID"), {
      target: { value: "anthropic.claude-sonnet" },
    });
    fireEvent.change(screen.getByLabelText("Environment variable"), {
      target: { value: "AWS_BEARER_TOKEN_BEDROCK" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save bedrock/i }));

    await waitFor(() =>
      expect(runSetupActionMock).toHaveBeenCalledWith("mac", {
        action: "add_bedrock",
        name: "bedrock",
        base_url: "https://bedrock-runtime.us-east-1.amazonaws.com",
        model: "anthropic.claude-sonnet",
        env_var: "AWS_BEARER_TOKEN_BEDROCK",
      }),
    );
    expect(screen.queryByRole("button", { name: /save bedrock/i })).toBeNull();
  });

  it("offers only supported guided commands and starts them with typed parameters", async () => {
    hosts = [online("mac")];
    inventories.set(
      "mac",
      inventory({ supported_operations: ["codex-login", "databricks-configure"] }),
    );
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: /^sign in$/i }));
    await waitFor(() =>
      expect(startSetupOperationMock).toHaveBeenCalledWith("mac", "codex-login", {}),
    );
    expect(screen.getAllByRole("button", { name: /sign in unavailable/i }).length).toBeGreaterThan(
      0,
    );

    fireEvent.change(screen.getByLabelText("Workspace URL"), {
      target: { value: "https://workspace.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^configure$/i }));
    await waitFor(() =>
      expect(startSetupOperationMock).toHaveBeenCalledWith("mac", "databricks-configure", {
        workspace_url: "https://workspace.example.com",
        agents: ["claude", "codex"],
      }),
    );
  });

  it("writes harness keys and per-harness model settings through typed actions", async () => {
    hosts = [online("mac")];
    inventories.set("mac", inventory());
    renderSection();

    fireEvent.click((await screen.findAllByRole("button", { name: /^add key$/i }))[0]);
    fireEvent.change(screen.getByLabelText("Environment variable"), {
      target: { value: "CURSOR_API_KEY" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save key/i }));
    await waitFor(() =>
      expect(runSetupActionMock).toHaveBeenCalledWith("mac", {
        action: "set_harness_key",
        harness: "cursor",
        env_var: "CURSOR_API_KEY",
      }),
    );

    fireEvent.change(screen.getByLabelText(/^OpenCode default model/), {
      target: { value: "openai/gpt-5.6" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save model/i }));
    await waitFor(() =>
      expect(runSetupActionMock).toHaveBeenCalledWith("mac", {
        action: "set_opencode_model",
        model: "openai/gpt-5.6",
      }),
    );
  });

  it("shows the host removal warning and waits for confirmation", async () => {
    hosts = [online("mac")];
    inventories.set(
      "mac",
      inventory({
        providers: [
          {
            name: "risky-gateway",
            kind: "gateway",
            families: ["openai"],
            defaults: [],
            default_scopes: ["openai"],
            credential_sources: {},
            models: {},
            base_urls: {},
            remove_warning: "Existing sessions will retain this gateway until they stop.",
          },
        ],
      }),
    );
    renderSection();

    await screen.findByText("risky-gateway");
    fireEvent.click(screen.getByRole("button", { name: /^remove$/i }));
    expect(screen.getByRole("alertdialog", { name: /remove risky-gateway/i })).toHaveTextContent(
      "Existing sessions will retain this gateway until they stop.",
    );
    expect(runSetupActionMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /remove provider/i }));
    await waitFor(() =>
      expect(runSetupActionMock).toHaveBeenCalledWith("mac", {
        action: "remove_provider",
        name: "risky-gateway",
      }),
    );
  });

  it("clears an open connection form when switching computers", async () => {
    hosts = [online("mac", "Mac"), online("linux", "Linux")];
    localStorage.setItem("omnigent:provider-settings-host", "mac");
    inventories.set("mac", inventory());
    inventories.set(
      "linux",
      inventory({
        providers: [
          {
            name: "linux-only",
            kind: "api_key",
            families: ["openai"],
            defaults: [],
            default_scopes: ["openai"],
            credential_sources: {},
            models: {},
            base_urls: {},
          },
        ],
      }),
    );
    renderSection();

    await screen.findByRole("button", { name: /add provider/i });
    fireEvent.click(screen.getByRole("button", { name: /add provider/i }));
    expect(screen.getByLabelText("Default model")).toBeInTheDocument();
    fireEvent.change(hostSelect(), { target: { value: "linux" } });
    expect(await screen.findByText("linux-only")).toBeInTheDocument();
    expect(screen.queryByLabelText("Default model")).toBeNull();
  });

  it("does not render an old computer's response after switching", async () => {
    let resolveMac!: (value: SetupInventory) => void;
    const macInventory = new Promise<SetupInventory>((resolve) => {
      resolveMac = resolve;
    });
    hosts = [online("mac", "Mac"), online("linux", "Linux")];
    localStorage.setItem("omnigent:provider-settings-host", "mac");
    inventories.set(
      "linux",
      inventory({
        providers: [
          {
            name: "linux-only",
            kind: "api_key",
            families: ["openai"],
            defaults: [],
            default_scopes: ["openai"],
            credential_sources: {},
            models: {},
            base_urls: {},
          },
        ],
      }),
    );
    fetchInventoryMock.mockImplementation((hostId) =>
      hostId === "mac" ? macInventory : Promise.resolve(inventories.get(hostId) ?? inventory()),
    );
    renderSection();

    await waitFor(() =>
      expect(fetchInventoryMock).toHaveBeenCalledWith("mac", expect.any(AbortSignal)),
    );
    fireEvent.change(hostSelect(), { target: { value: "linux" } });
    expect(await screen.findByText("linux-only")).toBeInTheDocument();
    resolveMac(
      inventory({
        providers: [
          {
            name: "stale-mac-provider",
            kind: "api_key",
            families: ["openai"],
            defaults: [],
            default_scopes: ["openai"],
            credential_sources: {},
            models: {},
            base_urls: {},
          },
        ],
      }),
    );
    await waitFor(() => expect(screen.queryByText("stale-mac-provider")).toBeNull());
  });
});
