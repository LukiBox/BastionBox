"""Gradual theme cross-fade — swap the look without a jarring flash.

Applying a new stylesheet + palette is instantaneous and, on a big color swing
like dark→light, looks like a hard cut. This module wraps the swap in a short
cross-fade: it snapshots every visible top-level window, applies the change
*underneath* the snapshot, then fades the snapshot out — so the old look melts
into the new one over a couple hundred milliseconds.

It is best-effort and self-contained: if anything about the grab/animation fails,
the change is still applied (the snapshot step is skipped), so theming never
breaks because a fade couldn't run. Respects reduced-motion by simply applying
instantly when *duration* is 0.
"""
from __future__ import annotations

from typing import Callable

_MS = 260


def crossfade(app, apply_fn: Callable[[], None], duration: int = _MS) -> None:
    """Apply *apply_fn* (the theme swap) with a fade across visible windows."""
    if duration <= 0:
        apply_fn()
        return

    from PySide6.QtCore import QEasingCurve, QPropertyAnimation
    from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

    overlays = []
    try:
        for w in app.topLevelWidgets():
            if w.isVisible() and w.isWindow() and w.width() > 1 and w.height() > 1:
                snap = w.grab()
                lbl = QLabel(w)
                lbl.setPixmap(snap)
                lbl.setGeometry(0, 0, w.width(), w.height())
                lbl.setScaledContents(True)
                eff = QGraphicsOpacityEffect(lbl)
                lbl.setGraphicsEffect(eff)
                lbl.raise_()
                lbl.show()
                overlays.append((lbl, eff))
    except Exception:  # noqa: BLE001 - a failed grab must not block the swap
        overlays = []

    apply_fn()

    for lbl, eff in overlays:
        anim = QPropertyAnimation(eff, b"opacity", lbl)
        anim.setDuration(duration)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.finished.connect(lbl.deleteLater)
        # Keep a reference on the widget so the animation isn't GC'd mid-flight.
        lbl._fade_anim = anim
        anim.start()
