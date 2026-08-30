/**
 * Presentation for provider quota status.
 *
 * The one rule: never draw a number the provider did not report. A status with
 * no windows renders as "not reported", not as an empty meter — an empty meter
 * reads as "plenty left", which is the opposite of what silence means.
 */
import type { ProviderUsage, ProviderUsageState, ProviderUsageWindow } from "@/hooks/useHosts";

export type UsageTone = "ok" | "warning" | "error" | "muted";

export interface UsagePresentation {
  label: string;
  tone: UsageTone;
}

const PRESENTATION: Record<ProviderUsageState, UsagePresentation> = {
  available: { label: "Available", tone: "ok" },
  partially_used: { label: "Partially used", tone: "ok" },
  nearly_exhausted: { label: "Nearly exhausted", tone: "warning" },
  exhausted: { label: "Exhausted", tone: "error" },
  unknown: { label: "Not reported", tone: "muted" },
  authentication_required: { label: "Authentication required", tone: "warning" },
  provider_unavailable: { label: "Provider unavailable", tone: "error" },
};

/** How to render a usage state. */
export function usagePresentation(state: ProviderUsageState): UsagePresentation {
  return PRESENTATION[state] ?? PRESENTATION.unknown;
}

/** The tone for one window's bar, from how much of it is gone. */
export function windowTone(usedPercent: number): UsageTone {
  if (usedPercent >= 100) return "error";
  if (usedPercent >= 90) return "warning";
  return "ok";
}

/** Clamp a reported percentage into a drawable width without changing the text. */
export function barWidthPercent(usedPercent: number): number {
  if (!Number.isFinite(usedPercent)) return 0;
  return Math.min(100, Math.max(0, usedPercent));
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}

/**
 * Describe when a window resets, relative to now.
 *
 * @param resetsAt Unix seconds, or null when the provider reported none.
 * @param nowMs Current time in ms, injected so this stays testable.
 */
export function resetLabel(resetsAt: number | null, nowMs: number): string | null {
  if (resetsAt === null || !Number.isFinite(resetsAt)) return null;
  const seconds = Math.round(resetsAt - nowMs / 1000);
  if (seconds <= 0) return "resets now";
  if (seconds < 3600) return `resets in ${plural(Math.max(1, Math.round(seconds / 60)), "minute")}`;
  if (seconds < 86400) return `resets in ${plural(Math.round(seconds / 3600), "hour")}`;
  return `resets in ${plural(Math.round(seconds / 86400), "day")}`;
}

/**
 * Say how old a reading is, so a cached number never passes for a live one.
 *
 * @param checkedAt Unix seconds the host took the reading.
 * @param nowMs Current time in ms.
 */
export function checkedLabel(checkedAt: number, nowMs: number): string | null {
  if (!checkedAt || !Number.isFinite(checkedAt)) return null;
  const seconds = Math.max(0, Math.round(nowMs / 1000 - checkedAt));
  if (seconds < 60) return "checked just now";
  if (seconds < 3600) return `checked ${plural(Math.round(seconds / 60), "minute")} ago`;
  if (seconds < 86400) return `checked ${plural(Math.round(seconds / 3600), "hour")} ago`;
  return `checked ${plural(Math.round(seconds / 86400), "day")} ago`;
}

/** Whether there is a number worth drawing at all. */
export function hasReportedWindows(usage: ProviderUsage | null | undefined): boolean {
  return !!usage && usage.windows.length > 0;
}

/** The windows to draw, worst first, so the binding limit reads first. */
export function orderedWindows(usage: ProviderUsage): ProviderUsageWindow[] {
  return [...usage.windows].sort((a, b) => b.used_percent - a.used_percent);
}
