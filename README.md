# Accent-aware text selection: real browser evidence

These files were captured from the actual Omnigent web application through Codex browser interaction. No application UI was drawn or reconstructed.

- Main baseline: `9dc015e1dadf6e65a7f4b2c8f74b06ac9d38cccb`.
- Candidate capture: `0d61e2ed5ab82b7a00ba57aeaa611807447b6ebd` (same selection patch subsequently rebased for publication).
- Settings → Appearance. Both versions select the exact sentence “Choose how Omnigent looks on this device.”
- `github-dark-*`: GitHub preset, Dark mode. The before band is faint; the candidate band uses the palette accent.
- `orange-dark-*`: custom accent `#FF8900`, Dark mode. Candidate keeps the chosen orange because it has enough contrast.
- `yellow-light-*`: custom accent `#FFFFCC`, Light mode. Candidate darkens the selection shade to keep it visible; the saved accent remains pale yellow.
- `github-main.mp4` and `github-candidate.mp4`: genuine timed browser frame recordings, about 7 seconds for main and 13 seconds for candidate. Main selects around 1.4 seconds and copies around 5.2 seconds; candidate selects around 6.1 seconds and copies around 9.9 seconds; clipboard content was verified in both versions. No audio, synthetic frames, or replacement UI. Frame cadence reflects browser capture speed.

Screenshots show Settings only, with no private session content. Main screenshots have a shorter viewport than candidate screenshots; compare the selected sentence below the Appearance heading. The code PR does not merge this evidence branch.
