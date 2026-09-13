interface AntigravityTranscriptFallbackNoticeProps {
  labels?: Readonly<Record<string, string>> | null;
}

export function AntigravityTranscriptFallbackNotice({
  labels,
}: AntigravityTranscriptFallbackNoticeProps) {
  if (labels?.antigravity_native_transcript_fallback !== "1") return null;

  return (
    <div
      role="status"
      data-testid="antigravity-transcript-fallback-notice"
      className="mx-3 border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-foreground"
    >
      Antigravity approval prompts appear in Terminal; respond there to continue.
    </div>
  );
}
