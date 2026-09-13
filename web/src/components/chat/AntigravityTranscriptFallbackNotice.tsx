export function AntigravityTranscriptFallbackNotice({
  terminalAvailable,
}: {
  terminalAvailable: boolean;
}) {
  return (
    <div
      role="status"
      data-testid="antigravity-transcript-fallback-notice"
      className="mx-3 border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-foreground"
    >
      Antigravity approval prompts appear in Terminal; respond there to continue.
      {!terminalAvailable && (
        <span className="ml-1 text-muted-foreground">
          Terminal is unavailable until this session reconnects.
        </span>
      )}
    </div>
  );
}
