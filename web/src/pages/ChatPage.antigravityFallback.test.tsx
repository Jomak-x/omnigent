import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AntigravityTranscriptFallbackNotice } from "@/components/chat/AntigravityTranscriptFallbackNotice";

describe("Antigravity transcript fallback notice", () => {
  it("shows terminal approval guidance when transcript fallback is active", () => {
    render(
      <AntigravityTranscriptFallbackNotice
        labels={{ antigravity_native_transcript_fallback: "1" }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "Antigravity approval prompts appear in Terminal; respond there to continue.",
    );
    expect(screen.getByRole("status")).not.toHaveTextContent("unavailable");
  });

  it.each([
    ["missing", undefined],
    ["disabled", { antigravity_native_transcript_fallback: "0" }],
  ])("hides the notice when the fallback label is %s", (_case, labels) => {
    const { rerender } = render(
      <AntigravityTranscriptFallbackNotice
        labels={{ antigravity_native_transcript_fallback: "1" }}
      />,
    );
    expect(screen.getByTestId("antigravity-transcript-fallback-notice")).toBeInTheDocument();

    rerender(<AntigravityTranscriptFallbackNotice labels={labels} />);

    expect(screen.queryByTestId("antigravity-transcript-fallback-notice")).toBeNull();
  });
});
