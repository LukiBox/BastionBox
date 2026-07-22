"""Reusable tactical UI atoms — the building blocks the pages compose from.

These wrap plain Qt widgets and apply the design-system properties from
:mod:`bastion.ui.theme` (via Qt dynamic properties + a repolish), so the look
stays entirely token-driven. A small ``HudFrame`` paints corner brackets for the
command-console feel without any external assets.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QVBoxLayout, QWidget)


def _repolish(w: QWidget) -> None:
    """Re-evaluate the stylesheet after a dynamic property changes."""
    w.style().unpolish(w)
    w.style().polish(w)


def set_prop(w: QWidget, name: str, value) -> QWidget:
    w.setProperty(name, value)
    _repolish(w)
    return w


class StencilLabel(QLabel):
    """An uppercase, wide-tracked section header — the stenciled callout."""

    def __init__(self, text: str, role: str = "stencil", parent=None):
        super().__init__(text.upper() if role == "stencil" else text, parent)
        self.setProperty("role", role)


class StatusPill(QLabel):
    """A compact status chip: SECURE / ARMED / BLOCKED / OFFLINE."""

    def __init__(self, text: str = "SECURE", status: str = "secure", parent=None):
        super().__init__(text, parent)
        self.setProperty("pill", "true")
        self.setProperty("status", status)
        self.setAlignment(Qt.AlignCenter)

    def set_status(self, text: str, status: str) -> None:
        self.setText(text)
        self.setProperty("status", status)
        _repolish(self)


class Card(QFrame):
    """A titled panel with optional stenciled header, holding a vertical layout."""

    def __init__(self, title: str = "", parent=None, well: bool = False):
        super().__init__(parent)
        self.setProperty("role", "well" if well else "card")
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(16, 14, 16, 16)
        self._v.setSpacing(10)
        if title:
            header = QHBoxLayout()
            self._title_label = StencilLabel(title)
            header.addWidget(self._title_label)
            header.addStretch(1)
            self._header = header
            self._v.addLayout(header)

    def set_title(self, title: str) -> None:
        """Replace the stenciled header text (live language switching)."""
        if hasattr(self, "_title_label"):
            self._title_label.setText(title.upper())

    def body(self) -> QVBoxLayout:
        return self._v

    def add(self, w: QWidget) -> QWidget:
        self._v.addWidget(w)
        return w

    def add_header_widget(self, w: QWidget) -> None:
        if hasattr(self, "_header"):
            self._header.addWidget(w)


class HudFrame(QFrame):
    """A frame that paints four corner brackets — the HUD/targeting motif.

    Purely decorative and cheap: it draws L-shaped strokes at each corner in the
    brand color. Used to frame the hero/status area without importing images.
    """

    def __init__(self, color: str = "#54806C", parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._len = 18
        self._inset = 6

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(self._color)
        pen.setWidth(2)
        painter.setPen(pen)
        r = self.rect().adjusted(self._inset, self._inset,
                                 -self._inset, -self._inset)
        L = self._len
        # Top-left
        painter.drawLine(r.left(), r.top(), r.left() + L, r.top())
        painter.drawLine(r.left(), r.top(), r.left(), r.top() + L)
        # Top-right
        painter.drawLine(r.right(), r.top(), r.right() - L, r.top())
        painter.drawLine(r.right(), r.top(), r.right(), r.top() + L)
        # Bottom-left
        painter.drawLine(r.left(), r.bottom(), r.left() + L, r.bottom())
        painter.drawLine(r.left(), r.bottom(), r.left(), r.bottom() - L)
        # Bottom-right
        painter.drawLine(r.right(), r.bottom(), r.right() - L, r.bottom())
        painter.drawLine(r.right(), r.bottom(), r.right(), r.bottom() - L)
        painter.end()


class ContextMeter(QWidget):
    """Live tokens-used / window bar with a one-glance mono readout.

    Never silently lies about what the model can see: the label always shows the
    real numbers, and turns amber as the window fills so the user knows when to
    compact.
    """

    def __init__(self, window: int = 8192, parent=None):
        super().__init__(parent)
        self._window = window
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        row = QHBoxLayout()
        from ...core.i18n import t
        self._label = QLabel(t("meter.context").upper())
        self._label.setProperty("role", "readout")
        self._value = QLabel(f"0 / {window:,}")
        self._value.setProperty("role", "readout")
        row.addWidget(self._label)
        row.addStretch(1)
        row.addWidget(self._value)
        v.addLayout(row)
        self._bar = QProgressBar()
        self._bar.setRange(0, window)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        v.addWidget(self._bar)

    def retranslate(self) -> None:
        from ...core.i18n import t
        self._label.setText(t("meter.context").upper())

    def set_usage(self, used: int) -> None:
        used = max(0, min(used, self._window))
        self._bar.setValue(used)
        self._value.setText(f"{used:,} / {self._window:,}")

    def set_window(self, window: int) -> None:
        """Update the context ceiling live (e.g. after a bigger model loads)."""
        self._window = max(1, int(window))
        self._bar.setRange(0, self._window)
        self._value.setText(f"0 / {self._window:,}")


class ModelStatusBar(QWidget):
    """Bottom strip: loaded model, tokens/sec, VRAM — the tray-style readout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 6, 14, 6)
        self.pill = StatusPill("OFFLINE", "offline")
        self.model = QLabel("no model loaded")
        self.model.setProperty("role", "readout")
        self.perf = QLabel("—")
        self.perf.setProperty("role", "readout")
        row.addWidget(self.pill)
        row.addSpacing(12)
        row.addWidget(self.model)
        row.addStretch(1)
        row.addWidget(self.perf)

    def set_model(self, name: str, perf: str = "", status=("SECURE", "secure")) -> None:
        self.model.setText(name)
        self.perf.setText(perf or "—")
        self.pill.set_status(*status)
