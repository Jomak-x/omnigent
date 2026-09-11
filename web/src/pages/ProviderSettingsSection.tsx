import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangleIcon,
  ChevronDownIcon,
  CloudIcon,
  KeyRoundIcon,
  Loader2Icon,
  PlusIcon,
  ServerCogIcon,
  TerminalIcon,
  Trash2Icon,
  WandSparklesIcon,
} from "lucide-react";

import { ProviderSetupTerminal } from "@/components/ProviderSetupTerminal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useHosts, type Host } from "@/hooks/useHosts";
import { isFeatureEnabled } from "@/lib/capabilities";
import { useServerInfo } from "@/lib/CapabilitiesContext";
import {
  detectSetup,
  fetchSetupInventory,
  runSetupAction,
  startSetupOperation,
  type SetupAction,
  type SetupAcpAgent,
  type SetupDetection,
  type SetupDetectRequest,
  type SetupImportPreview,
  type SetupInventory,
  type SetupKeyProvider,
  type SetupOperation,
  type SetupOperationAction,
  type SetupProvider,
  type ProviderFamily,
  type ProviderSurface,
} from "@/lib/providerSetupApi";
import { HarnessSetupDialog } from "@/shell/HarnessSetupDialog";
import { cn } from "@/lib/utils";

const REMEMBERED_HOST_KEY = "omnigent:provider-settings-host";
const REMEMBERED_HOST_NAME_KEY = `${REMEMBERED_HOST_KEY}:name`;

const SETUP_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Gemini",
  pi: "Pi",
  environment: "environment variable",
  stored: "stored secret",
  inline: "inline value",
  command: "login command",
};

function setupLabel(value: string): string {
  return SETUP_LABELS[value] ?? value.replaceAll("_", " ");
}

function readRememberedHost(): string | null {
  try {
    return localStorage.getItem(REMEMBERED_HOST_KEY);
  } catch {
    return null;
  }
}

function readRememberedHostName(): string | null {
  try {
    return localStorage.getItem(REMEMBERED_HOST_NAME_KEY);
  } catch {
    return null;
  }
}

function rememberHost(hostId: string, name: string): void {
  try {
    localStorage.setItem(REMEMBERED_HOST_KEY, hostId);
    localStorage.setItem(REMEMBERED_HOST_NAME_KEY, name);
  } catch {
    // Storage can be unavailable in privacy-restricted embeds.
  }
}

export function ProviderSettingsSection() {
  const hostsQuery = useHosts({ refetchOnFocus: true });
  const hosts = hostsQuery.data;
  const [hostId, setHostId] = useState<string | null>(null);

  useEffect(() => {
    if (!hosts) return;
    if (hostId) return;
    const remembered = readRememberedHost();
    if (remembered) {
      setHostId(remembered);
      return;
    }
    if (hosts.length === 1) {
      setHostId(hosts[0].host_id);
    }
  }, [hostId, hosts]);

  const host = hosts?.find((candidate) => candidate.host_id === hostId) ?? null;
  const rememberedHostName = readRememberedHostName();
  const selectedHostMissing = !!hostId && !!hosts && !host;

  return (
    <section>
      <h1 className="text-2xl font-semibold">Providers</h1>
      <p className="mt-1 text-ui text-muted-foreground">
        Configure model providers and coding-agent authentication on a computer.
      </p>
      <div className="mt-6 flex flex-col gap-5">
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-ui font-medium">Computer</h2>
              <p className="text-sm text-muted-foreground">
                Provider settings stay on the computer that runs your agents.
              </p>
            </div>
            {hosts && hosts.length > 0 && (
              <Select
                value={hostId ?? undefined}
                onValueChange={(next) => {
                  setHostId(next);
                  const selected = hosts.find((candidate) => candidate.host_id === next);
                  rememberHost(next, selected?.name ?? next);
                }}
                componentId="settings.providers.host"
                valueHasNoPii={false}
              >
                <SelectTrigger
                  aria-label="Computer"
                  className="w-64"
                  data-testid="settings-providers-host"
                >
                  <SelectValue placeholder="Choose a computer" />
                </SelectTrigger>
                <SelectContent>
                  {selectedHostMissing && (
                    <SelectItem value={hostId} disabled>
                      {rememberedHostName ?? hostId} · unavailable
                    </SelectItem>
                  )}
                  {hosts.map((candidate) => (
                    <SelectItem key={candidate.host_id} value={candidate.host_id}>
                      {candidate.name} · {candidate.status}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          {hostsQuery.isPending && (
            <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2Icon className="size-4 animate-spin" /> Loading computers…
            </p>
          )}
          {hostsQuery.isError && (
            <InlineError
              message="Computers are unavailable."
              onRetry={() => void hostsQuery.refetch()}
            />
          )}
          {hosts && hosts.length === 0 && !selectedHostMissing && (
            <p className="mt-3 text-sm text-muted-foreground">
              Connect a computer with{" "}
              <code className="rounded bg-muted px-1 py-0.5">omni host</code> before configuring
              providers.
            </p>
          )}
          {hosts && hosts.length > 1 && !host && (
            <p className="mt-3 text-sm text-muted-foreground">
              {selectedHostMissing
                ? `${rememberedHostName ?? "The selected computer"} is unavailable. Choose another computer explicitly to change this selection.`
                : "Choose a computer. Omnigent will never move these settings to another computer automatically."}
            </p>
          )}
          {selectedHostMissing && hosts && hosts.length <= 1 && (
            <p className="mt-3 text-sm text-muted-foreground">
              {rememberedHostName ?? "The selected computer"} is unavailable. This page will not
              switch to another computer automatically.
            </p>
          )}
        </div>

        {host?.status === "offline" && (
          <div
            role="status"
            className="rounded-xl border border-amber-500/35 bg-amber-500/10 p-4 text-sm"
          >
            <div className="flex items-start gap-2">
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-amber-600" />
              <span>
                {host.name} is offline. Its settings cannot be read or changed until it reconnects;
                this selection will stay on {host.name}.
              </span>
            </div>
          </div>
        )}

        {host?.status === "online" && <ProviderHostSettings key={host.host_id} host={host} />}
      </div>
    </section>
  );
}

function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="mt-3 flex flex-wrap items-center gap-2 text-sm text-destructive">
      <AlertTriangleIcon className="size-4" />
      <span>{message}</span>
      {onRetry && (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

function ProviderHostSettings({ host }: { host: Host }) {
  const queryClient = useQueryClient();
  const info = useServerInfo();
  const queryKey = ["provider-setup", host.host_id] as const;
  const inventoryQuery = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchSetupInventory(host.host_id, signal),
    retry: false,
  });
  const actionMutation = useMutation({
    mutationFn: (action: SetupAction) => runSetupAction(host.host_id, action),
  });
  const detectionMutation = useMutation({
    mutationFn: (request?: SetupDetectRequest) => detectSetup(host.host_id, request),
  });
  const operationMutation = useMutation({
    mutationFn: ({
      action,
      parameters,
    }: {
      action: SetupOperationAction;
      parameters?: Record<string, unknown>;
    }) => startSetupOperation(host.host_id, action, parameters),
  });
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detection, setDetection] = useState<SetupDetection | null>(null);
  const [detectionRequest, setDetectionRequest] = useState<SetupDetectRequest | null>(null);
  const [operation, setOperation] = useState<SetupOperation | null>(null);

  const inventory = inventoryQuery.data;
  const serverGate = isFeatureEnabled(info, "harness_install");
  const canMutate = !!inventory && inventory.mutations_enabled !== false && serverGate;
  const busy = actionMutation.isPending || operationMutation.isPending;

  const act = async (action: SetupAction): Promise<boolean> => {
    setError(null);
    setNotice(null);
    try {
      const result = await actionMutation.mutateAsync(action);
      queryClient.setQueryData(queryKey, result.inventory);
      void queryClient.invalidateQueries({ queryKey });
      void queryClient.invalidateQueries({ queryKey: ["hosts"] });
      setNotice(result.message);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The setup change failed.");
      return false;
    }
  };

  const detect = async (request?: SetupDetectRequest) => {
    setError(null);
    setNotice(null);
    try {
      setDetection(await detectionMutation.mutateAsync(request));
      setDetectionRequest(request ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Detection failed.");
    }
  };

  const start = async (
    action: SetupOperationAction,
    parameters: Record<string, unknown> = {},
  ): Promise<boolean> => {
    setError(null);
    setNotice(null);
    try {
      setOperation(await operationMutation.mutateAsync({ action, parameters }));
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The guided setup could not start.");
      return false;
    }
  };

  if (inventoryQuery.isPending) {
    return (
      <div className="flex items-center gap-2 rounded-xl border bg-card p-5 text-sm text-muted-foreground">
        <Loader2Icon className="size-4 animate-spin" /> Loading provider settings from {host.name}…
      </div>
    );
  }
  if (inventoryQuery.isError || !inventory) {
    return (
      <div className="rounded-xl border bg-card p-4">
        <InlineError
          message={
            inventoryQuery.error instanceof Error
              ? inventoryQuery.error.message
              : `Provider settings are unavailable on ${host.name}.`
          }
          onRetry={() => void inventoryQuery.refetch()}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {!canMutate && (
        <div className="rounded-xl border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
          Provider setup changes are disabled on this server. You can still review the configuration
          reported by {host.name}.
        </div>
      )}
      {notice && (
        <div
          role="status"
          className="rounded-lg border border-success/40 bg-success/10 px-3 py-2 text-sm"
        >
          {notice}
        </div>
      )}
      {error && <InlineError message={error} />}
      {operation && (
        <ProviderSetupTerminal
          hostId={host.host_id}
          operation={operation}
          onOperationChange={setOperation}
          onFinished={() => {
            void inventoryQuery.refetch();
            void queryClient.invalidateQueries({ queryKey: ["hosts"] });
          }}
        />
      )}

      <ProviderOverview
        inventory={inventory}
        canMutate={canMutate}
        busy={busy}
        detection={detection}
        detecting={detectionMutation.isPending}
        onDetect={() => void detect()}
        onAction={act}
      />
      <ProviderForms
        inventory={inventory}
        detection={detection}
        canMutate={canMutate}
        busy={busy}
        onAction={act}
      />
      <HarnessSettings
        host={host}
        inventory={inventory}
        canMutate={canMutate}
        busy={busy}
        detection={detection}
        onAction={act}
        onStart={start}
      />
      <AdvancedSettings
        inventory={inventory}
        detection={detection}
        detectionRequest={detectionRequest}
        canMutate={canMutate}
        busy={busy}
        onAction={act}
        onDetectImport={(request) => void detect(request)}
        detecting={detectionMutation.isPending}
      />
    </div>
  );
}

function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="rounded-xl border border-border bg-card">{children}</div>
    </section>
  );
}

function StatusBadge({ children, good = false }: { children: React.ReactNode; good?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs",
        good
          ? "border-success/35 bg-success/10 text-success-foreground"
          : "border-border bg-muted/60 text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

function providerSurfaces(provider: SetupProvider): ProviderSurface[] {
  const raw = provider.default_scopes?.length
    ? provider.default_scopes
    : provider.surfaces?.length
      ? provider.surfaces
      : provider.families;
  const surfaces = raw.filter((surface): surface is ProviderSurface =>
    ["anthropic", "openai", "gemini", "pi"].includes(surface),
  );
  if (provider.families.some((family) => family === "anthropic" || family === "openai")) {
    surfaces.push("pi");
  }
  return [...new Set(surfaces)];
}

function ProviderOverview({
  inventory,
  canMutate,
  busy,
  detection,
  detecting,
  onDetect,
  onAction,
}: {
  inventory: SetupInventory;
  canMutate: boolean;
  busy: boolean;
  detection: SetupDetection | null;
  detecting: boolean;
  onDetect: () => void;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  const [removing, setRemoving] = useState<SetupProvider | null>(null);
  return (
    <SectionCard
      title="Connections"
      description="Named credentials and gateways available to new agent processes."
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b p-4">
        <p className="text-sm text-muted-foreground">
          This overview reads local configuration only. “Configured locally” means a provider entry
          is saved; it does not verify a vendor account or token. Detection runs only when you ask
          for it.
        </p>
        {canMutate && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            loading={detecting}
            data-testid="settings-provider-detect"
            onClick={onDetect}
          >
            <WandSparklesIcon className="size-4" /> Detect credentials
          </Button>
        )}
      </div>
      {inventory.providers.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">No providers are configured.</p>
      ) : (
        <div className="divide-y">
          {inventory.providers.map((provider) => (
            <ProviderRow
              key={provider.name}
              provider={provider}
              effectiveDefaults={inventory.effective_defaults}
              canMutate={canMutate}
              busy={busy}
              onDefault={(surface) =>
                void onAction({ action: "set_default", name: provider.name, surface })
              }
              onRemove={() => setRemoving(provider)}
              onAction={onAction}
            />
          ))}
        </div>
      )}
      {detection && (
        <DetectionResults
          detection={detection}
          dismissed={inventory.dismissed_detections}
          canMutate={canMutate}
          busy={busy}
          onAction={onAction}
        />
      )}
      {removing && (
        <ConfirmRemoval
          provider={removing}
          busy={busy}
          onCancel={() => setRemoving(null)}
          onConfirm={async () => {
            if (await onAction({ action: "remove_provider", name: removing.name })) {
              setRemoving(null);
            }
          }}
        />
      )}
    </SectionCard>
  );
}

function ProviderRow({
  provider,
  effectiveDefaults,
  canMutate,
  busy,
  onDefault,
  onRemove,
  onAction,
}: {
  provider: SetupProvider;
  effectiveDefaults: Record<string, string | null>;
  canMutate: boolean;
  busy: boolean;
  onDefault: (surface: ProviderSurface) => void;
  onRemove: () => void;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  const surfaces = providerSurfaces(provider);
  const [surface, setSurface] = useState<ProviderSurface>(surfaces[0] ?? "openai");
  const [credentialOpen, setCredentialOpen] = useState(false);
  const [secret, setSecret] = useState("");
  const [envVar, setEnvVar] = useState("");
  const credentialFamilies = provider.families.filter((family): family is ProviderFamily =>
    ["anthropic", "openai", "gemini"].includes(family),
  );
  const effective = Object.entries(effectiveDefaults)
    .filter(([, name]) => name === provider.name)
    .map(([scope]) => scope);
  return (
    <div className="flex flex-col gap-3 p-4" data-testid={`provider-row-${provider.name}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{provider.name}</span>
            <StatusBadge good>Configured locally</StatusBadge>
            <StatusBadge>{provider.kind.replaceAll("_", " ")}</StatusBadge>
            {provider.defaults.map((item) => (
              <StatusBadge key={item} good>
                Default for {setupLabel(item)}
              </StatusBadge>
            ))}
            {effective
              .filter((item) => !provider.defaults.includes(item))
              .map((item) => (
                <StatusBadge key={`effective-${item}`}>
                  Effective for {setupLabel(item)}
                </StatusBadge>
              ))}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {provider.families.length > 0 && (
              <span>{provider.families.map(setupLabel).join(" + ")}</span>
            )}
            {Object.entries(provider.credential_sources).map(([family, source]) => (
              <span key={`credential-${family}`}>
                {setupLabel(family)} credential: {setupLabel(source)}
              </span>
            ))}
            {Object.entries(provider.models).map(([family, model]) => (
              <span key={family}>
                {setupLabel(family)}: {model}
              </span>
            ))}
            {Object.values(provider.base_urls).map((url) => (
              <span key={url} className="max-w-full truncate">
                {url}
              </span>
            ))}
          </div>
        </div>
        {canMutate && (
          <div className="flex flex-wrap items-center gap-2">
            {surfaces.length > 0 && (
              <>
                <Select
                  value={surface}
                  onValueChange={(next) => setSurface(next as ProviderSurface)}
                >
                  <SelectTrigger
                    aria-label={`Default scope for ${provider.name}`}
                    className="h-8 w-32"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {surfaces.map((item) => (
                      <SelectItem key={item} value={item}>
                        {setupLabel(item)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={() => onDefault(surface)}
                >
                  Make default
                </Button>
              </>
            )}
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onRemove}>
              <Trash2Icon className="size-4" /> Remove
            </Button>
            {credentialFamilies.length > 0 && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => setCredentialOpen((open) => !open)}
              >
                Update credential
              </Button>
            )}
          </div>
        )}
      </div>
      {credentialOpen && canMutate && (
        <form
          className="flex flex-col gap-3 rounded-lg border bg-muted/20 p-3"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!(secret.trim() || envVar.trim())) return;
            if (
              await onAction({
                action: "update_provider_credential",
                name: provider.name,
                families: credentialFamilies,
                ...credentialPayload(secret, envVar),
              })
            ) {
              setSecret("");
              setEnvVar("");
              setCredentialOpen(false);
            }
          }}
        >
          <SecretOrEnvironment
            secret={secret}
            envVar={envVar}
            onSecret={setSecret}
            onEnvVar={setEnvVar}
          />
          <p className="text-xs text-muted-foreground">
            Only the credential source changes. Models, endpoints, defaults, and advanced fields
            stay intact.
          </p>
          <div>
            <Button
              type="submit"
              size="sm"
              loading={busy}
              disabled={!(secret.trim() || envVar.trim())}
            >
              Save credential
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

function ConfirmRemoval({
  provider,
  busy,
  onCancel,
  onConfirm,
}: {
  provider: SetupProvider;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="border-t border-destructive/30 bg-destructive/5 p-4"
      role="alertdialog"
      aria-label={`Remove ${provider.name}`}
    >
      <div className="flex items-start gap-2">
        <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-destructive" />
        <div className="flex-1">
          <p className="text-sm font-medium">Remove {provider.name}?</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {provider.remove_warning ??
              "New processes will no longer use this connection. Running processes keep their current environment until they exit."}
          </p>
          <div className="mt-3 flex gap-2">
            <Button
              type="button"
              size="sm"
              variant="destructive"
              loading={busy}
              onClick={onConfirm}
            >
              Remove provider
            </Button>
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DetectionResults({
  detection,
  dismissed,
  canMutate,
  busy,
  onAction,
}: {
  detection: SetupDetection;
  dismissed: string[];
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  return (
    <div className="border-t bg-muted/20 p-4" data-testid="provider-detection-results">
      <h3 className="text-sm font-medium">Detected on this computer</h3>
      {detection.warnings?.map((warning) => (
        <p key={warning} className="mt-2 text-sm text-amber-700 dark:text-amber-400">
          {warning}
        </p>
      ))}
      {detection.providers.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">No additional credentials were found.</p>
      ) : (
        <div className="mt-2 divide-y rounded-lg border bg-card">
          {detection.providers.map((provider) => {
            const ignored = dismissed.includes(provider.name);
            return (
              <div
                key={provider.name}
                className="flex flex-wrap items-center justify-between gap-3 p-3"
              >
                <div>
                  <div className="text-sm font-medium">
                    {provider.display_name ?? provider.name}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {setupLabel(provider.family)} · {setupLabel(provider.source)}
                  </div>
                </div>
                {canMutate && (
                  <div className="flex gap-2">
                    {ignored ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void onAction({
                            action: "dismiss_detection",
                            name: provider.name,
                            dismissed: false,
                          })
                        }
                      >
                        Show again
                      </Button>
                    ) : (
                      <>
                        <Button
                          type="button"
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            void onAction({ action: "adopt_detected", name: provider.name })
                          }
                        >
                          Use credential
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          onClick={() =>
                            void onAction({
                              action: "dismiss_detection",
                              name: provider.name,
                              dismissed: true,
                            })
                          }
                        >
                          Ignore
                        </Button>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ProviderForms({
  inventory,
  detection,
  canMutate,
  busy,
  onAction,
}: {
  inventory: SetupInventory;
  detection: SetupDetection | null;
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  const [open, setOpen] = useState<"key" | "gateway" | "bedrock" | null>(null);
  if (!canMutate) return null;
  return (
    <SectionCard
      title="Add a connection"
      description="Keys stay in the host credential store; saved settings only contain a reference."
    >
      <div className="flex flex-wrap gap-2 p-4">
        <Button
          type="button"
          variant={open === "key" ? "secondary" : "outline"}
          onClick={() => setOpen(open === "key" ? null : "key")}
        >
          <KeyRoundIcon className="size-4" /> Add provider
        </Button>
        <Button
          type="button"
          variant={open === "gateway" ? "secondary" : "outline"}
          onClick={() => setOpen(open === "gateway" ? null : "gateway")}
        >
          <CloudIcon className="size-4" /> Add gateway
        </Button>
        <Button
          type="button"
          variant={open === "bedrock" ? "secondary" : "outline"}
          onClick={() => setOpen(open === "bedrock" ? null : "bedrock")}
        >
          <ServerCogIcon className="size-4" /> Add Bedrock
        </Button>
      </div>
      {open && (
        <div className="border-t p-4">
          {open === "key" && (
            <KeyProviderForm
              catalog={inventory.key_providers}
              defaultModels={detection?.default_models ?? {}}
              busy={busy}
              onAction={onAction}
              onDone={() => setOpen(null)}
            />
          )}
          {open === "gateway" && (
            <GatewayForm busy={busy} onAction={onAction} onDone={() => setOpen(null)} />
          )}
          {open === "bedrock" && (
            <BedrockForm busy={busy} onAction={onAction} onDone={() => setOpen(null)} />
          )}
        </div>
      )}
    </SectionCard>
  );
}

function SecretOrEnvironment({
  secret,
  envVar,
  onSecret,
  onEnvVar,
}: {
  secret: string;
  envVar: string;
  onSecret: (value: string) => void;
  onEnvVar: (value: string) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="flex flex-col gap-1 text-sm font-medium">
        API key or token
        <Input
          type="password"
          autoComplete="off"
          value={secret}
          onChange={(event) => onSecret(event.target.value)}
          placeholder="Stored securely"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium">
        Environment variable
        <Input
          value={envVar}
          onChange={(event) => onEnvVar(event.target.value)}
          placeholder="Or use OPENAI_API_KEY"
        />
      </label>
    </div>
  );
}

function credentialPayload(secret: string, envVar: string): { secret?: string; env_var?: string } {
  return envVar.trim() ? { env_var: envVar.trim() } : { secret: secret.trim() };
}

function KeyProviderForm({
  catalog,
  defaultModels,
  busy,
  onAction,
  onDone,
}: {
  catalog: SetupKeyProvider[];
  defaultModels: Record<string, string | null>;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
  onDone: () => void;
}) {
  const [provider, setProvider] = useState(catalog[0]?.id ?? "");
  const [name, setName] = useState("");
  const [model, setModel] = useState(defaultModels[catalog[0]?.id ?? ""] ?? "");
  const [secret, setSecret] = useState("");
  const [envVar, setEnvVar] = useState("");
  const valid = provider && model.trim() && (secret.trim() || envVar.trim());
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!valid) return;
        if (
          await onAction({
            action: "add_key",
            provider,
            name: name.trim() || undefined,
            model: model.trim(),
            ...credentialPayload(secret, envVar),
          })
        ) {
          setSecret("");
          setEnvVar("");
          onDone();
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm font-medium">
          Vendor
          <Select
            value={provider}
            onValueChange={(next) => {
              setProvider(next);
              setModel(defaultModels[next] ?? "");
            }}
          >
            <SelectTrigger aria-label="Vendor">
              <SelectValue placeholder="Choose vendor" />
            </SelectTrigger>
            <SelectContent>
              {catalog.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Connection name
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Optional custom name"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Default model
          <Input
            required
            value={model}
            onChange={(event) => setModel(event.target.value)}
            placeholder="Required model ID"
          />
        </label>
      </div>
      <SecretOrEnvironment
        secret={secret}
        envVar={envVar}
        onSecret={setSecret}
        onEnvVar={setEnvVar}
      />
      <p className="text-xs text-muted-foreground">
        Using an existing connection name updates its credential while preserving compatible
        advanced settings.
      </p>
      <div>
        <Button type="submit" loading={busy} disabled={!valid}>
          Save provider
        </Button>
      </div>
    </form>
  );
}

function GatewayForm({
  busy,
  onAction,
  onDone,
}: {
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [envVar, setEnvVar] = useState("");
  const [anthropic, setAnthropic] = useState(true);
  const [openai, setOpenai] = useState(true);
  const [wire, setWire] = useState<"chat" | "responses">("responses");
  const [anthropicModel, setAnthropicModel] = useState("");
  const [openaiModel, setOpenaiModel] = useState("");
  const valid =
    name.trim() &&
    url.trim() &&
    (anthropic || openai) &&
    (!anthropic || anthropicModel.trim()) &&
    (!openai || openaiModel.trim()) &&
    (secret.trim() || envVar.trim());
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!valid) return;
        const models: Record<string, string> = {};
        if (anthropicModel.trim()) models.anthropic = anthropicModel.trim();
        if (openaiModel.trim()) models.openai = openaiModel.trim();
        if (
          await onAction({
            action: "add_gateway",
            name: name.trim(),
            base_url: url.trim(),
            families: [anthropic ? "anthropic" : null, openai ? "openai" : null].filter(
              (item): item is "anthropic" | "openai" => item !== null,
            ),
            wire_api: wire,
            models,
            ...credentialPayload(secret, envVar),
          })
        ) {
          setSecret("");
          setEnvVar("");
          onDone();
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm font-medium">
          Gateway name
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Base URL
          <Input
            inputMode="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://gateway.example.com"
          />
        </label>
      </div>
      <div className="flex flex-wrap gap-5 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={anthropic}
            onChange={(e) => setAnthropic(e.target.checked)}
          />{" "}
          Anthropic family
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={openai} onChange={(e) => setOpenai(e.target.checked)} />{" "}
          OpenAI family
        </label>
        <label className="flex items-center gap-2">
          OpenAI protocol
          <Select value={wire} onValueChange={(v) => setWire(v as "chat" | "responses")}>
            <SelectTrigger className="h-8 w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="responses">Responses</SelectItem>
              <SelectItem value="chat">Chat</SelectItem>
            </SelectContent>
          </Select>
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm font-medium">
          Anthropic model
          <Input
            disabled={!anthropic}
            value={anthropicModel}
            onChange={(e) => setAnthropicModel(e.target.value)}
            placeholder="Model ID"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          OpenAI model
          <Input
            disabled={!openai}
            value={openaiModel}
            onChange={(e) => setOpenaiModel(e.target.value)}
            placeholder="Model ID"
          />
        </label>
      </div>
      <SecretOrEnvironment
        secret={secret}
        envVar={envVar}
        onSecret={setSecret}
        onEnvVar={setEnvVar}
      />
      <div>
        <Button type="submit" loading={busy} disabled={!valid}>
          Save gateway
        </Button>
      </div>
    </form>
  );
}

function BedrockForm({
  busy,
  onAction,
  onDone,
}: {
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
  onDone: () => void;
}) {
  const [name, setName] = useState("bedrock");
  const [url, setUrl] = useState("https://bedrock-runtime.us-east-1.amazonaws.com");
  const [model, setModel] = useState("");
  const [secret, setSecret] = useState("");
  const [envVar, setEnvVar] = useState("");
  const valid = name.trim() && url.trim() && model.trim() && (secret.trim() || envVar.trim());
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!valid) return;
        if (
          await onAction({
            action: "add_bedrock",
            name: name.trim(),
            base_url: url.trim(),
            model: model.trim(),
            ...credentialPayload(secret, envVar),
          })
        ) {
          setSecret("");
          setEnvVar("");
          onDone();
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm font-medium">
          Connection name
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Bedrock endpoint
          <Input inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Model ID
          <Input value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
      </div>
      <SecretOrEnvironment
        secret={secret}
        envVar={envVar}
        onSecret={setSecret}
        onEnvVar={setEnvVar}
      />
      <div>
        <Button type="submit" loading={busy} disabled={!valid}>
          Save Bedrock
        </Button>
      </div>
    </form>
  );
}

const GUIDED_HARNESSES: {
  id: string;
  label: string;
  action?: SetupOperationAction;
  logout?: SetupOperationAction;
}[] = [
  { id: "claude-native", label: "Claude Code", action: "claude-login", logout: "claude-logout" },
  { id: "codex-native", label: "Codex", action: "codex-login", logout: "codex-logout" },
  { id: "pi-native", label: "Pi" },
  { id: "cursor", label: "Cursor", action: "cursor-login", logout: "cursor-logout" },
  { id: "antigravity", label: "Antigravity", action: "antigravity-login" },
  { id: "copilot", label: "GitHub Copilot" },
  { id: "opencode", label: "OpenCode", action: "opencode-login" },
  { id: "qwen", label: "Qwen", action: "qwen-configure" },
  { id: "goose", label: "Goose", action: "goose-configure" },
  { id: "hermes", label: "Hermes", action: "hermes-configure" },
  { id: "kiro", label: "Kiro", action: "kiro-login" },
  { id: "kimi", label: "Kimi", action: "kimi-login" },
];

function operationAvailable(
  inventory: SetupInventory,
  host: Host,
  action: SetupOperationAction,
  harness?: string,
): boolean {
  if (inventory.supported_operations) return inventory.supported_operations.includes(action);
  if (!harness) return true;
  const readiness = host.configured_harnesses;
  if (!readiness) return true;
  const status = readiness[harness] ?? readiness[harness.replace(/-native$/, "")];
  return status !== false;
}

function guidedActionLabel(action: SetupOperationAction): string {
  return action.endsWith("-login") ? "Sign in" : "Configure";
}

function HarnessSettings({
  host,
  inventory,
  canMutate,
  busy,
  detection,
  onAction,
  onStart,
}: {
  host: Host;
  inventory: SetupInventory;
  canMutate: boolean;
  busy: boolean;
  detection: SetupDetection | null;
  onAction: (action: SetupAction) => Promise<boolean>;
  onStart: (action: SetupOperationAction, parameters?: Record<string, unknown>) => Promise<boolean>;
}) {
  const [setupHarness, setSetupHarness] = useState<{ id: string; label: string } | null>(null);
  return (
    <SectionCard
      title="Agent authentication"
      description="Install agents, sign in to vendor CLIs, or use a host-stored key."
    >
      <div className="divide-y">
        <SubscriptionRow
          label="Pi original authentication"
          onStart={() => void onAction({ action: "subscription", cli: "pi" })}
          canMutate={canMutate}
          busy={busy}
          direct
        />
        {(["cursor", "antigravity", "copilot"] as const).map((harness) => (
          <HarnessKeyRow
            key={harness}
            harness={harness}
            configured={inventory.harness_settings[`${harness}_key_configured`]}
            canMutate={canMutate}
            busy={busy}
            onAction={onAction}
          />
        ))}
        <CopilotHostRow
          value={inventory.harness_settings.copilot_host ?? ""}
          canMutate={canMutate}
          busy={busy}
          onAction={onAction}
        />
        <OpenCodeModelRow
          value={inventory.harness_settings.opencode_model ?? ""}
          models={detection?.models.opencode ?? []}
          canMutate={canMutate}
          busy={busy}
          onAction={onAction}
        />
        <DatabricksGuidedRow
          canMutate={canMutate}
          available={operationAvailable(inventory, host, "databricks-configure")}
          busy={busy}
          onStart={onStart}
        />
        {GUIDED_HARNESSES.map((item) => (
          <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div>
              <div className="text-sm font-medium">{item.label}</div>
              <div className="text-xs text-muted-foreground">
                Install, readiness, and vendor instructions for this computer.
              </div>
            </div>
            {canMutate && (
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setSetupHarness(item)}
                >
                  Setup
                </Button>
                {item.action &&
                  (operationAvailable(inventory, host, item.action, item.id) ? (
                    <Button
                      type="button"
                      size="sm"
                      disabled={busy}
                      onClick={() => void onStart(item.action!)}
                    >
                      <TerminalIcon className="size-4" /> {guidedActionLabel(item.action)}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      disabled
                      title="Install this agent on the selected computer before starting its vendor setup."
                    >
                      {guidedActionLabel(item.action)} unavailable
                    </Button>
                  ))}
                {item.logout &&
                  (operationAvailable(inventory, host, item.logout, item.id) ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => void onStart(item.logout!)}
                    >
                      Sign out
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled
                      title="This vendor sign-out command is unavailable on the selected computer."
                    >
                      Sign out unavailable
                    </Button>
                  ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <HarnessSetupDialog
        open={setupHarness !== null}
        onOpenChange={(open) => {
          if (!open) setSetupHarness(null);
        }}
        agentName={setupHarness?.label}
        harness={setupHarness?.id ?? null}
        host={host}
      />
    </SectionCard>
  );
}

function SubscriptionRow({
  label,
  canMutate,
  busy,
  onStart,
  direct = false,
}: {
  label: string;
  canMutate: boolean;
  busy: boolean;
  onStart: () => void;
  direct?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 p-4">
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">
          {direct
            ? "Use Pi's original provider without a browser login."
            : "Complete the vendor-owned login in an embedded terminal."}
        </div>
      </div>
      {canMutate && (
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onStart}>
          {direct ? "Use subscription" : "Sign in"}
        </Button>
      )}
    </div>
  );
}

function HarnessKeyRow({
  harness,
  configured,
  canMutate,
  busy,
  onAction,
}: {
  harness: "cursor" | "antigravity" | "copilot";
  configured: boolean;
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [secret, setSecret] = useState("");
  const [envVar, setEnvVar] = useState("");
  return (
    <div className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium capitalize">
            {harness} key {configured && <StatusBadge good>Configured locally</StatusBadge>}
          </div>
          <div className="text-xs text-muted-foreground">
            A local configuration marker only; Omnigent does not claim the vendor account is
            authenticated.
          </div>
        </div>
        {canMutate && (
          <div className="flex gap-2">
            <Button type="button" size="sm" variant="outline" onClick={() => setOpen(!open)}>
              {configured ? "Replace key" : "Add key"}
            </Button>
            {configured && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => void onAction({ action: "remove_harness_key", harness })}
              >
                Remove
              </Button>
            )}
          </div>
        )}
      </div>
      {open && canMutate && (
        <form
          className="mt-3 flex flex-col gap-3 rounded-lg border bg-muted/20 p-3"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!(secret.trim() || envVar.trim())) return;
            if (
              await onAction({
                action: "set_harness_key",
                harness,
                ...credentialPayload(secret, envVar),
              })
            ) {
              setSecret("");
              setEnvVar("");
              setOpen(false);
            }
          }}
        >
          <SecretOrEnvironment
            secret={secret}
            envVar={envVar}
            onSecret={setSecret}
            onEnvVar={setEnvVar}
          />
          <div>
            <Button
              type="submit"
              size="sm"
              loading={busy}
              disabled={!(secret.trim() || envVar.trim())}
            >
              Save key
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

function CopilotHostRow({
  value,
  canMutate,
  busy,
  onAction,
}: {
  value: string;
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  const [host, setHost] = useState(value);
  return (
    <form
      className="flex flex-wrap items-end justify-between gap-3 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        void onAction({ action: "set_copilot_host", host: host.trim() || null });
      }}
    >
      <label className="flex min-w-64 flex-1 flex-col gap-1 text-sm font-medium">
        Copilot Enterprise host
        <span className="text-xs font-normal text-muted-foreground">
          Leave blank for github.com.
        </span>
        <Input
          disabled={!canMutate}
          value={host}
          onChange={(e) => setHost(e.target.value)}
          placeholder="github.example.com"
        />
      </label>
      {canMutate && (
        <Button type="submit" size="sm" variant="outline" loading={busy}>
          Save host
        </Button>
      )}
    </form>
  );
}

function OpenCodeModelRow({
  value,
  models,
  canMutate,
  busy,
  onAction,
}: {
  value: string;
  models: string[];
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  const [model, setModel] = useState(value);
  return (
    <form
      className="flex flex-wrap items-end justify-between gap-3 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        void onAction({ action: "set_opencode_model", model: model.trim() || null });
      }}
    >
      <label className="flex min-w-64 flex-1 flex-col gap-1 text-sm font-medium">
        OpenCode default model
        <span className="text-xs font-normal text-muted-foreground">
          Applies to new OpenCode processes. Clear it to let OpenCode choose.
        </span>
        <Input
          disabled={!canMutate}
          list="opencode-models"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="provider/model"
        />
        <datalist id="opencode-models">
          {models.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      </label>
      {canMutate && (
        <Button type="submit" size="sm" variant="outline" loading={busy}>
          Save model
        </Button>
      )}
    </form>
  );
}

function DatabricksGuidedRow({
  canMutate,
  available,
  busy,
  onStart,
}: {
  canMutate: boolean;
  available: boolean;
  busy: boolean;
  onStart: (action: SetupOperationAction, parameters?: Record<string, unknown>) => Promise<boolean>;
}) {
  const [workspace, setWorkspace] = useState("");
  const [agents, setAgents] = useState(["claude", "codex"]);
  const toggle = (agent: string) =>
    setAgents((items) =>
      items.includes(agent) ? items.filter((item) => item !== agent) : [...items, agent],
    );
  return (
    <form
      className="flex flex-col gap-3 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!available || !workspace.trim() || agents.length === 0) return;
        void onStart("databricks-configure", { workspace_url: workspace.trim(), agents });
      }}
    >
      <div>
        <div className="text-sm font-medium">Databricks workspace provider</div>
        <div className="text-xs text-muted-foreground">
          The vendor flow runs in the terminal; saved state is refreshed after it exits.
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-64 flex-1 flex-col gap-1 text-sm font-medium">
          Workspace URL
          <Input
            disabled={!canMutate || !available}
            inputMode="url"
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
            placeholder="https://workspace.cloud.databricks.com"
          />
        </label>
        <div className="flex gap-3 pb-2 text-sm">
          {["claude", "codex", "opencode"].map((agent) => (
            <label key={agent} className="flex items-center gap-1.5 capitalize">
              <input
                disabled={!canMutate || !available}
                type="checkbox"
                checked={agents.includes(agent)}
                onChange={() => toggle(agent)}
              />
              {agent}
            </label>
          ))}
        </div>
        {canMutate && available && (
          <Button
            type="submit"
            size="sm"
            loading={busy}
            disabled={!workspace.trim() || agents.length === 0}
          >
            <TerminalIcon className="size-4" /> Configure
          </Button>
        )}
        {canMutate && !available && (
          <span className="pb-2 text-xs text-muted-foreground">
            Unavailable until the Databricks setup prerequisites are installed on this computer.
          </span>
        )}
      </div>
    </form>
  );
}

function AdvancedSettings({
  inventory,
  detection,
  detectionRequest,
  canMutate,
  busy,
  onAction,
  onDetectImport,
  detecting,
}: {
  inventory: SetupInventory;
  detection: SetupDetection | null;
  detectionRequest: SetupDetectRequest | null;
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
  onDetectImport: (request: SetupDetectRequest) => void;
  detecting: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <SectionCard title="Advanced" description="Custom ACP agents and configuration imports.">
      <button
        type="button"
        className="flex w-full items-center justify-between p-4 text-left text-sm font-medium"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        Advanced provider tools
        <ChevronDownIcon className={cn("size-4 transition-transform", expanded && "rotate-180")} />
      </button>
      {expanded && (
        <div className="border-t">
          <AcpForm canMutate={canMutate} busy={busy} onAction={onAction} />
          <AcpList
            agents={inventory.acp_agents}
            canMutate={canMutate}
            busy={busy}
            onAction={onAction}
          />
          <ImportDetectionForm
            canMutate={canMutate}
            detecting={detecting}
            onDetect={onDetectImport}
          />
          <ImportPreviewList
            imports={detection?.imports ?? []}
            detectionRequest={detectionRequest}
            canMutate={canMutate}
            busy={busy}
            onAction={onAction}
          />
        </div>
      )}
    </SectionCard>
  );
}

function ImportDetectionForm({
  canMutate,
  detecting,
  onDetect,
}: {
  canMutate: boolean;
  detecting: boolean;
  onDetect: (request: SetupDetectRequest) => void;
}) {
  const [source, setSource] = useState<"openclaw" | "acpx">("openclaw");
  const [path, setPath] = useState("");
  if (!canMutate) return null;
  return (
    <form
      className="flex flex-wrap items-end gap-3 border-t p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!path.trim()) return;
        onDetect({ import_source: source, import_path: path.trim() });
      }}
    >
      <label className="flex flex-col gap-1 text-sm font-medium">
        Import format
        <Select value={source} onValueChange={(value) => setSource(value as "openclaw" | "acpx")}>
          <SelectTrigger className="w-36" aria-label="Import format">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="openclaw">OpenClaw</SelectItem>
            <SelectItem value="acpx">acpx</SelectItem>
          </SelectContent>
        </Select>
      </label>
      <label className="flex min-w-64 flex-1 flex-col gap-1 text-sm font-medium">
        Configuration path
        <Input
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder="Path on the selected computer"
        />
      </label>
      <Button type="submit" variant="outline" loading={detecting} disabled={!path.trim()}>
        Preview import
      </Button>
    </form>
  );
}

function AcpForm({
  canMutate,
  busy,
  onAction,
}: {
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [model, setModel] = useState("");
  const [env, setEnv] = useState("");
  const [mode, setMode] = useState<"server" | "client">("server");
  const [sendModel, setSendModel] = useState(false);
  const [mcp, setMcp] = useState(true);
  const [system, setSystem] = useState(true);
  if (!canMutate) return null;
  return (
    <form
      className="flex flex-col gap-3 p-4"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!name.trim() || !command.trim()) return;
        if (
          await onAction({
            action: "add_acp",
            name: name.trim(),
            command: command.trim(),
            model: model.trim() || undefined,
            env_passthrough: env
              .split(/[\n,]/)
              .map((item) => item.trim())
              .filter(Boolean),
            session_id_mode: mode,
            send_model: sendModel,
            omnigent_mcp: mcp,
            inject_system_prompt: system,
          })
        ) {
          setName("");
          setCommand("");
          setModel("");
          setEnv("");
        }
      }}
    >
      <h3 className="text-sm font-medium">Add custom ACP agent</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          Name
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Model
          <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="Optional" />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        Launch command
        <Textarea
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder="my-agent --acp"
          rows={2}
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Environment variables to pass through
        <Input
          value={env}
          onChange={(e) => setEnv(e.target.value)}
          placeholder="NAME_ONE, NAME_TWO"
        />
      </label>
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2">
          Session IDs
          <Select value={mode} onValueChange={(v) => setMode(v as "server" | "client")}>
            <SelectTrigger className="h-8 w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="server">Server</SelectItem>
              <SelectItem value="client">Client</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <ToggleLabel label="Send model" value={sendModel} onChange={setSendModel} />
        <ToggleLabel label="Omnigent MCP" value={mcp} onChange={setMcp} />
        <ToggleLabel label="System prompt" value={system} onChange={setSystem} />
      </div>
      <div>
        <Button type="submit" loading={busy} disabled={!name.trim() || !command.trim()}>
          <PlusIcon className="size-4" /> Add ACP agent
        </Button>
      </div>
    </form>
  );
}

function ToggleLabel({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2">
      {label}
      <Switch checked={value} onCheckedChange={onChange} />
    </label>
  );
}

function AcpList({
  agents,
  canMutate,
  busy,
  onAction,
}: {
  agents: SetupAcpAgent[];
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  if (agents.length === 0)
    return <p className="border-t p-4 text-sm text-muted-foreground">No custom ACP agents.</p>;
  return (
    <div className="divide-y border-t">
      {agents.map((agent) => (
        <div key={agent.slug} className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <div className="text-sm font-medium">{agent.name}</div>
            <code className="text-xs text-muted-foreground">{agent.command}</code>
            {agent.model && (
              <div className="text-xs text-muted-foreground">Model: {agent.model}</div>
            )}
          </div>
          {canMutate && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => void onAction({ action: "remove_acp", slug: agent.slug })}
            >
              <Trash2Icon className="size-4" /> Remove
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}

function ImportPreviewList({
  imports,
  detectionRequest,
  canMutate,
  busy,
  onAction,
}: {
  imports: SetupImportPreview[];
  detectionRequest: SetupDetectRequest | null;
  canMutate: boolean;
  busy: boolean;
  onAction: (action: SetupAction) => Promise<boolean>;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const groups = useMemo(
    () => ({
      openclaw: imports.filter((item) => item.source === "openclaw"),
      acpx: imports.filter((item) => item.source === "acpx"),
    }),
    [imports],
  );
  if (imports.length === 0)
    return (
      <p className="border-t p-4 text-sm text-muted-foreground">
        Run detection to preview OpenClaw or acpx agents. Credentials are never imported.
      </p>
    );
  return (
    <div className="border-t p-4">
      <h3 className="text-sm font-medium">Import preview</h3>
      <p className="text-xs text-muted-foreground">
        Review launch commands before importing. No credentials are copied.
      </p>
      {(["openclaw", "acpx"] as const).map(
        (source) =>
          groups[source].length > 0 && (
            <div key={source} className="mt-3 rounded-lg border">
              <div className="border-b px-3 py-2 text-sm font-medium capitalize">{source}</div>
              {groups[source].map((item) => (
                <label
                  key={`${source}:${item.name}`}
                  className="flex items-start gap-2 border-b p-3 last:border-b-0"
                >
                  <input
                    type="checkbox"
                    disabled={!canMutate}
                    checked={selected.includes(`${source}:${item.name}`)}
                    onChange={(e) =>
                      setSelected((old) =>
                        e.target.checked
                          ? [...old, `${source}:${item.name}`]
                          : old.filter((entry) => entry !== `${source}:${item.name}`),
                      )
                    }
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{item.name}</span>
                    <code className="block truncate text-xs text-muted-foreground">
                      {item.command}
                    </code>
                  </span>
                </label>
              ))}
              {canMutate && (
                <div className="border-t p-3">
                  <Button
                    type="button"
                    size="sm"
                    disabled={
                      busy ||
                      !groups[source].some((item) => selected.includes(`${source}:${item.name}`))
                    }
                    onClick={() =>
                      void (() => {
                        const chosen = groups[source].filter((item) =>
                          selected.includes(`${source}:${item.name}`),
                        );
                        return onAction({
                          action: "import_acp",
                          source,
                          names: chosen.map((item) => item.name),
                          path:
                            detectionRequest?.import_source === source
                              ? detectionRequest.import_path
                              : undefined,
                          fingerprints: Object.fromEntries(
                            chosen.map((item) => [item.name, item.fingerprint]),
                          ),
                        });
                      })()
                    }
                  >
                    Import selected {source} agents
                  </Button>
                </div>
              )}
            </div>
          ),
      )}
    </div>
  );
}
