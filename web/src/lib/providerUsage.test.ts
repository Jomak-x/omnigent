import { describe, expect, it } from "vitest";
import {
  barWidthPercent,
  checkedLabel,
  hasReportedWindows,
  orderedWindows,
  resetLabel,
  usagePresentation,
  windowTone,
} from "./providerUsage";
import type { ProviderUsage } from "@/hooks/useHosts";

const NOW_MS = 1_788_112_841_000;

function usage(partial: Partial<ProviderUsage> = {}): ProviderUsage {
  return {
    provider_id: "codex",
    profile: null,
    state: "exhausted",
    windows: [],
    plan: "plus",
    message: null,
    checked_at: NOW_MS / 1000,
    ...partial,
  };
}

describe("usage presentation", () => {
  it("labels every state, including the ones with no numbers", () => {
    for (const state of [
      "available",
      "partially_used",
      "nearly_exhausted",
      "exhausted",
      "unknown",
      "authentication_required",
      "provider_unavailable",
    ] as const) {
      expect(usagePresentation(state).label).not.toBe("");
    }
    expect(usagePresentation("unknown").label).toBe("Not reported");
    expect(usagePresentation("unknown").tone).toBe("muted");
  });

  it("escalates a window's tone as it fills", () => {
    expect(windowTone(10)).toBe("ok");
    expect(windowTone(89.9)).toBe("ok");
    expect(windowTone(90)).toBe("warning");
    expect(windowTone(100)).toBe("error");
  });

  it("clamps a bar without touching the reported number", () => {
    expect(barWidthPercent(140)).toBe(100);
    expect(barWidthPercent(-3)).toBe(0);
    expect(barWidthPercent(Number.NaN)).toBe(0);
    expect(barWidthPercent(47)).toBe(47);
  });
});

describe("resetLabel", () => {
  it("describes the wait in the largest useful unit", () => {
    expect(resetLabel(NOW_MS / 1000 + 90, NOW_MS)).toBe("resets in 2 minutes");
    expect(resetLabel(NOW_MS / 1000 + 3 * 3600, NOW_MS)).toBe("resets in 3 hours");
    expect(resetLabel(NOW_MS / 1000 + 2 * 86400, NOW_MS)).toBe("resets in 2 days");
    expect(resetLabel(NOW_MS / 1000 + 3600, NOW_MS)).toBe("resets in 1 hour");
  });

  it("says nothing when the provider reported no reset time", () => {
    expect(resetLabel(null, NOW_MS)).toBeNull();
  });

  it("does not show a negative wait for a window that already reset", () => {
    expect(resetLabel(NOW_MS / 1000 - 500, NOW_MS)).toBe("resets now");
  });
});

describe("checkedLabel", () => {
  it("keeps the age of a cached reading visible", () => {
    expect(checkedLabel(NOW_MS / 1000, NOW_MS)).toBe("checked just now");
    expect(checkedLabel(NOW_MS / 1000 - 300, NOW_MS)).toBe("checked 5 minutes ago");
    expect(checkedLabel(NOW_MS / 1000 - 7200, NOW_MS)).toBe("checked 2 hours ago");
    expect(checkedLabel(0, NOW_MS)).toBeNull();
  });
});

describe("reported windows", () => {
  it("treats a status with no windows as nothing to draw", () => {
    expect(hasReportedWindows(usage())).toBe(false);
    expect(hasReportedWindows(null)).toBe(false);
    expect(
      hasReportedWindows(
        usage({
          windows: [
            {
              id: "primary",
              label: "5-hour limit",
              used_percent: 12,
              window_minutes: 300,
              resets_at: null,
            },
          ],
        }),
      ),
    ).toBe(true);
  });

  it("puts the binding limit first", () => {
    const ordered = orderedWindows(
      usage({
        windows: [
          {
            id: "secondary",
            label: "Weekly limit",
            used_percent: 47,
            window_minutes: 10080,
            resets_at: null,
          },
          {
            id: "primary",
            label: "5-hour limit",
            used_percent: 100,
            window_minutes: 300,
            resets_at: null,
          },
        ],
      }),
    );

    expect(ordered.map((w) => w.id)).toEqual(["primary", "secondary"]);
  });
});
