/**
 * Pre-session provider status for the "Configure …" modal.
 *
 * Answers the question a New Chat cannot otherwise answer until the session is
 * already running: *which provider will serve this agent, and is it in a state
 * to do the work?* The harness→provider mapping is resolved host-side by the
 * same function a launch uses (`default_for_harnesses` on the inventory row),
 * so nothing is re-derived here.
 *
 * Quota is shown only from a reading the host already has. Taking a fresh one
 * can start a vendor CLI, so it happens on an explicit press, never on open.
 */
import { AlertTriangleIcon, CircleCheckIcon, CircleDashedIcon, RefreshCwIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  useProviderInventory,
  useProviderUsage,
  useRefreshProviderUsage,
  type Host,
  type ProviderInventoryEntry,
} from "@/hooks/useHosts";
import { providerConnectionState, providerStatePresentation } from "@/lib/providerConnection";
import {
  checkedLabel,
  hasReportedWindows,
  orderedWindows,
  resetLabel,
  usagePresentation,
  type UsageTone,
} from "@/lib/providerUsage";

const TONE_TEXT: Record<UsageTone, string> = {
  ok: "text-foreground",
  warning: "text-amber-600 dark:text-amber-500",
  error: "text-destructive",
  muted: "text-muted-foreground",
};

/** The row that would serve *harness*, or null when the host names none. */
export function providerForHarness(
  providers: readonly ProviderInventoryEntry[] | undefined,
  harness: string | null,
): ProviderInventoryEntry | null {
  if (!harness || !providers) return null;
  return providers.find((p) => (p.default_for_harnesses ?? []).includes(harness)) ?? null;
}

function UsageLine({ hostId, provider }: { hostId: string; provider: ProviderInventoryEntry }) {
  // `enabled: false` — a cached reading is shown, but opening this modal must
  // never itself start a probe on the host.
  const { data: usage } = useProviderUsage(hostId, provider.id, false);
  const refresh = useRefreshProviderUsage(hostId, provider.id);
  const now = Date.now();

  if (!usage) {
    return (
      <Button
        variant="outline"
        size="sm"
        className="mt-1.5 h-7 gap-1.5"
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending}
        data-testid="new-chat-provider-usage-check"
      >
        <RefreshCwIcon className={`size-3 ${refresh.isPending ? "animate-spin" : ""}`} />
        {refresh.isPending ? "Checking usage…" : "Check usage"}
      </Button>
    );
  }

  const presentation = usagePresentation(usage.state);
  const checked = checkedLabel(usage.checked_at, now);
  return (
    <div className="mt-1.5 text-sm" data-testid="new-chat-provider-usage" data-state={usage.state}>
      <div className="flex flex-wrap items-center gap-x-2">
        <span className={TONE_TEXT[presentation.tone]}>{presentation.label}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 gap-1.5 px-1.5 text-xs"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          data-testid="new-chat-provider-usage-check"
        >
          <RefreshCwIcon className={`size-3 ${refresh.isPending ? "animate-spin" : ""}`} />
          Re-check
        </Button>
      </div>
      {hasReportedWindows(usage) ? (
        <ul className="mt-0.5 text-muted-foreground">
          {orderedWindows(usage).map((window) => {
            const resets = resetLabel(window.resets_at, now);
            return (
              <li key={window.id} data-testid={`new-chat-provider-window-${window.id}`}>
                {window.label}: {Math.round(window.used_percent)}% used
                {resets ? ` · ${resets}` : ""}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-0.5 text-muted-foreground">
          {usage.message ?? "This provider reported no usage limits."}
        </p>
      )}
      {checked && <p className="mt-0.5 text-xs text-muted-foreground">{checked}</p>}
    </div>
  );
}

/**
 * Name the provider that will serve *harness* on *host*, with its state.
 *
 * Renders nothing when there is no host (a sandbox session is provisioned
 * server-side) or when the host names no provider for this harness — an
 * invented "unknown provider" row would be noise, not information.
 */
export function NewChatProviderStatus({
  host,
  harness,
  open,
}: {
  host: Host | null | undefined;
  harness: string | null;
  open: boolean;
}) {
  const hostId = host?.host_id ?? null;
  const { data: providers } = useProviderInventory(hostId, open && !!hostId);
  const provider = providerForHarness(providers, harness);
  // A sandbox session is provisioned server-side, so there is no host whose
  // providers could answer; say nothing rather than name the wrong machine's.
  if (!hostId || !provider) return null;

  const state = providerConnectionState(provider);
  const presentation = providerStatePresentation(state);
  const Icon =
    presentation.tone === "ok"
      ? CircleCheckIcon
      : presentation.tone === "muted"
        ? CircleDashedIcon
        : AlertTriangleIcon;
  return (
    <div data-testid="new-chat-provider-status" data-state={state}>
      <div className="flex flex-wrap items-center gap-1.5 text-ui">
        <Icon
          className={`size-4 shrink-0 ${
            presentation.tone === "ok"
              ? "text-emerald-600 dark:text-emerald-500"
              : TONE_TEXT[presentation.tone]
          }`}
        />
        <span className="font-medium">{provider.display_name}</span>
        <span className={`text-sm ${TONE_TEXT[presentation.tone]}`}>{presentation.label}</span>
      </div>
      {presentation.actionable && provider.connection_detail && (
        <p className="mt-0.5 text-sm text-muted-foreground">{provider.connection_detail}</p>
      )}
      {provider.capabilities.usage_status === "supported" && hostId && (
        <UsageLine hostId={hostId} provider={provider} />
      )}
    </div>
  );
}
