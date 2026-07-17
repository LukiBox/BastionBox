"""Vector line icons, tinted at render time — no emoji, no image assets.

A tiny icon system: each icon is Lucide-style SVG path data (24×24 grid,
2px round strokes) rendered through QtSvg into a crisp, DPI-aware pixmap in
whatever color the current palette needs. Nav buttons get a two-state icon
(normal color + on-accent color when the pill is active) so the active state
reads correctly on the gradient fill.

Rendering is cached by (name, color, size) — theme switches just ask for the
new color and get a fresh tint.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Lucide path data (ISC licensed), 24x24 viewBox, stroke-only.
_ICONS: dict[str, str] = {
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "grid": ('<rect width="7" height="7" x="3" y="3" rx="1.5"/>'
             '<rect width="7" height="7" x="14" y="3" rx="1.5"/>'
             '<rect width="7" height="7" x="14" y="14" rx="1.5"/>'
             '<rect width="7" height="7" x="3" y="14" rx="1.5"/>'),
    "cpu": ('<rect x="4" y="4" width="16" height="16" rx="2"/>'
            '<rect x="9" y="9" width="6" height="6"/>'
            '<path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/>'
            '<path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/>'
            '<path d="M9 2v2"/><path d="M9 20v2"/>'),
    "book": ('<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
             '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>'),
    "shield": ('<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 '
               '20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 '
               '1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'),
    "gear": ('<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 '
             '2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 '
             '2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 '
             '0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 '
             '0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 '
             '2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 '
             '2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 '
             '1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 '
             '.73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 '
             '0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
             '<circle cx="12" cy="12" r="3"/>'),
    "send": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "history": ('<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
                '<path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>'),
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "minus": '<path d="M5 12h14"/>',
    "square": '<rect width="14" height="14" x="5" y="5" rx="2"/>',
    "restore": ('<rect width="10" height="10" x="4" y="10" rx="2"/>'
                '<path d="M8 6h10a2 2 0 0 1 2 2v10"/>'),
    "compress": ('<path d="m4 10 8-6 8 6"/><path d="m4 16 8 6 8-6"/>'),
    "box": ('<path d="m7.5 4.27 9 5.15"/>'
            '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 '
            '0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>'
            '<path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>'),
    "folder": ('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 '
               '1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 '
               '0 2 2Z"/>'),
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "file-text": ('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 '
                  '0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
                  '<path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>'),
    "user-pen": ('<path d="M11.5 15H7a4 4 0 0 0-4 4v2"/>'
                 '<path d="M21.4 10.6a2.1 2.1 0 0 0-3-3l-3.9 3.9a2 2 0 0 '
                 '0-.5.8l-.8 2.4a.5.5 0 0 0 .6.6l2.4-.8a2 2 0 0 0 '
                 '.8-.5z"/><circle cx="10" cy="7" r="4"/>'),
}


def _svg(name: str, color: str) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'{_ICONS[name]}</svg>').encode()


_cache: dict[tuple[str, str, int], QPixmap] = {}


def pixmap(name: str, color: str, size: int = 20) -> QPixmap:
    """Render icon *name* tinted *color* at *size* (device-independent px)."""
    key = (name, color, size)
    if key in _cache:
        return _cache[key]
    scale = 2  # render at 2x so high-DPI screens stay crisp
    img = QImage(size * scale, size * scale, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    QSvgRenderer(_svg(name, color)).render(
        painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(scale)
    _cache[key] = pm
    return pm


def icon(name: str, color: str, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def nav_icon(name: str, off_color: str, on_color: str, size: int = 20) -> QIcon:
    """Two-state icon: *off_color* normally, *on_color* when checked/active."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, off_color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, on_color, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, on_color, size), QIcon.Active, QIcon.On)
    return ic
