import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AntigravityTranscriptFallbackNotice } from "@/components/chat/AntigravityTranscriptFallbackNotice";

describe("Antigravity transcript fallback notice", () => {
  it("keeps terminal approval guidance visible when the terminal is available", () => {
    render(<AntigravityTranscriptFallbackNotice terminalAvailable />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Antigravity approval prompts appear in Terminal; respond there to continue.",
    );
    expect(screen.getByRole("status")).not.toHaveTextContent("unavailable");
  });

  it("explains when the required terminal cannot currently be opened", () => {
    render(<AntigravityTranscriptFallbackNotice terminalAvailable={false} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Terminal is unavailable until this session reconnects.",
    );
  });
});
