Optional bundled fonts
======================

BastionBox's tactical look asks for Orbitron (stenciled HUD headings) and
JetBrains Mono (readouts), then falls back to Windows-native faces (Bahnschrift,
Cascadia Mono, Consolas) so nothing is required.

To bundle the preferred fonts for a pixel-identical look on any machine, drop the
.ttf files here:

    Orbitron-Bold.ttf
    Orbitron-Black.ttf
    JetBrainsMono-Regular.ttf
    JetBrainsMono-Medium.ttf

They are loaded via QFontDatabase.addApplicationFont at startup when present.
Both families are open-source (SIL Open Font License) and can be carried onto an
air-gapped site by media — no download.
