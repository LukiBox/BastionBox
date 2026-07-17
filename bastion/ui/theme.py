"""The BastionBox visual system — calm sage command console, in QSS.

The design language (v2, after the LukiBox redesign) is a *soft tactical* look:
a gentle sage-green gradient backdrop, floating white (or deep green-gray)
rounded panels, one teal-green gradient accent for the active/primary elements,
and quiet, low-contrast hairlines. Military heritage survives in the stenciled
readouts (SECURE CHANNEL, CONTEXT) and the strict accent semantics —

    brand (sage teal) → identity / primary / active   (calm authority)
    secure green      → verified / OK
    amber             → ARMED / caution
    soft signal red   → BLOCKED / destructive

Everything is token-driven: :func:`build_qss` renders a full Qt stylesheet from
a :class:`Palette`, so dark and light are the *same* design with swapped tokens —
no per-widget hardcoded colors. Fonts degrade gracefully to stock Windows faces.
"""
from __future__ import annotations

from dataclasses import dataclass

# Font stacks. The wordmark/headings use a clean condensed face; readouts stay
# monospaced for the tactical feel; body text is a humanist sans.
HEADING_FONT = '"Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold", "Arial", sans-serif'
MONO_FONT = '"JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New", monospace'
BODY_FONT = '"Segoe UI", "Inter", "Roboto", system-ui, sans-serif'


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str            # window backdrop (gradient start)
    bg2: str           # window backdrop (gradient end)
    surface: str       # the main content canvas
    surface2: str      # cards, buttons, inputs, bubbles (elevated)
    overlay: str       # sunken wells, code blocks
    border: str        # hairlines
    border_strong: str # emphasized dividers / input borders
    text: str          # primary text
    text_dim: str      # secondary / labels
    text_faint: str    # tertiary / disabled
    brand: str         # sage teal (gradient end / pressed)
    brand_hi: str      # lighter sage (gradient start / hover)
    brand_tint: str    # translucent-looking tint for chips & hovers
    secure: str        # verified green
    amber: str         # armed / caution
    danger: str        # blocked / destructive
    info: str          # readout teal-cyan
    on_accent: str     # text on brand/danger fills


DARK = Palette(
    name="dark",
    bg="#101815",
    bg2="#182420",
    surface="#1A2521",
    surface2="#233029",
    overlay="#141D19",
    border="#2C3B34",
    border_strong="#3C4F45",
    text="#E5EEE8",
    text_dim="#9CB0A5",
    text_faint="#68796F",
    brand="#4F8570",
    brand_hi="#649B83",
    brand_tint="#26382F",
    secure="#54BD82",
    amber="#D9A44A",
    danger="#DF7373",
    info="#63AEC2",
    on_accent="#FFFFFF",
)

LIGHT = Palette(
    name="light",
    bg="#CFE0D6",          # sage backdrop — the soft green wash behind panels
    bg2="#E6EFE9",
    surface="#F2F5F2",     # main canvas — near-white with a green whisper
    surface2="#FFFFFF",    # cards / bubbles / inputs float in white
    overlay="#E9F0EB",
    border="#DFE7E1",
    border_strong="#C7D4CB",
    text="#22312B",
    text_dim="#5C6E65",
    text_faint="#93A49A",
    brand="#54806C",
    brand_hi="#6FA28E",
    brand_tint="#DCEAE2",
    secure="#358A57",
    amber="#B9791A",
    danger="#C75454",
    info="#3A7F92",
    on_accent="#FFFFFF",
)

THEMES = {"dark": DARK, "light": LIGHT}

# The palette currently applied to the app. Widgets that build *inline* styles
# (chat code blocks, diff coloring, …) must read this at render time instead of
# capturing a palette at construction — otherwise a live theme switch leaves
# them painted in the previous theme's colors (the old "light theme looks
# broken after switching" bug).
_current: Palette = DARK


def set_current_palette(p: Palette) -> None:
    global _current
    _current = p


def current_palette() -> Palette:
    return _current


def qpalette(p: Palette):
    """Build a Qt :class:`QPalette` from *p*.

    QSS only colors the widgets we name; Qt paints everything *un*styled —
    scroll-area viewports, bare ``QDialog`` backgrounds, item views — from the
    application QPalette. Without this, on a dark-mode Windows box those regions
    fall back to the system's black palette (the "black box" behind the chat and
    the theme picker). Setting the palette from the theme makes every surface,
    styled or not, agree with the look.
    """
    from PySide6.QtGui import QColor, QPalette

    def c(hex_color: str) -> QColor:
        return QColor(hex_color)

    pal = QPalette()
    pal.setColor(QPalette.Window, c(p.surface))
    pal.setColor(QPalette.WindowText, c(p.text))
    pal.setColor(QPalette.Base, c(p.surface))          # scroll viewports, views
    pal.setColor(QPalette.AlternateBase, c(p.surface2))
    pal.setColor(QPalette.Text, c(p.text))
    pal.setColor(QPalette.PlaceholderText, c(p.text_faint))
    pal.setColor(QPalette.Button, c(p.surface2))
    pal.setColor(QPalette.ButtonText, c(p.text))
    pal.setColor(QPalette.BrightText, c(p.on_accent))
    pal.setColor(QPalette.Highlight, c(p.brand))
    pal.setColor(QPalette.HighlightedText, c(p.on_accent))
    pal.setColor(QPalette.ToolTipBase, c(p.surface2))
    pal.setColor(QPalette.ToolTipText, c(p.text))
    pal.setColor(QPalette.Link, c(p.info))
    # Disabled group: dim text so greyed-out controls read as disabled.
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, c(p.text_faint))
    return pal


def grad(a: str, b: str, vertical: bool = True) -> str:
    """A two-stop linear gradient in QSS syntax (top→bottom by default)."""
    x2, y2 = (0, 1) if vertical else (1, 0)
    return (f"qlineargradient(x1:0, y1:0, x2:{x2}, y2:{y2}, "
            f"stop:0 {a}, stop:1 {b})")


def rgba(hex_color: str, alpha: int) -> str:
    """``#RRGGBB`` + alpha (0-255) → a QSS ``rgba(...)`` string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def build_qss(p: Palette) -> str:
    """Render the full application stylesheet for palette *p*."""
    accent = grad(p.brand_hi, p.brand)            # the teal-green pill/CTA fill
    return f"""
* {{
    font-family: {BODY_FONT};
    font-size: 14px;
    color: {p.text};
    outline: 0;
}}
QMainWindow, QWidget#Root {{
    background: {grad(p.bg, p.bg2, vertical=False)};
}}

/* ---- The floating content canvas ------------------------------------ */
QFrame#Canvas {{
    background: {p.surface};
    border: 1px solid {rgba(p.border_strong, 110)};
    border-radius: 18px;
}}

/* ---- Custom title bar (frameless window chrome) ----------------------- */
QWidget#TitleBar {{
    background: transparent;
}}
QLabel#TitleText {{
    color: {p.text_dim};
    font-size: 13px;
    background: transparent;
}}
QPushButton#WinBtn, QPushButton#WinBtnClose {{
    background: transparent;
    border: 0;
    border-radius: 8px;
    padding: 0;
}}
QPushButton#WinBtn:hover {{ background: {rgba(p.surface2, 170)}; }}
QPushButton#WinBtn:pressed {{ background: {rgba(p.surface2, 230)}; }}
QPushButton#WinBtnClose:hover {{ background: {p.danger}; }}
QPushButton#WinBtnClose:pressed {{ background: {rgba(p.danger, 200)}; }}

/* ---- Assistant avatar chip ---------------------------------------------- */
QLabel#Avatar {{
    background: {p.brand_tint};
    border: 1px solid {rgba(p.brand, 70)};
    border-radius: 9px;
}}

/* ---- Sidebar (sits directly on the sage gradient) -------------------- */
QWidget#Sidebar {{
    background: transparent;
}}
QLabel#Wordmark {{
    font-family: {HEADING_FONT};
    font-size: 27px;
    letter-spacing: 2px;
    color: {p.text};
    padding: 2px 0;
}}
QLabel#WordmarkTag {{
    font-size: 12px;
    letter-spacing: 1px;
    color: {p.text_dim};
    padding-bottom: 2px;
}}
QPushButton#NavItem {{
    text-align: left;
    padding: 11px 16px;
    border: 0;
    border-radius: 12px;
    background: transparent;
    color: {p.text};
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#NavItem:hover {{
    background: {rgba(p.surface2, 150)};
}}
QPushButton#NavItem:checked {{
    background: {accent};
    color: {p.on_accent};
}}

/* ---- Section headers / stenciled readouts ---------------------------- */
QLabel[role="stencil"] {{
    font-family: {HEADING_FONT};
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 3px;
    color: {p.text_dim};
    text-transform: uppercase;
}}
QLabel[role="h1"] {{
    font-family: {HEADING_FONT};
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 1px;
    color: {p.text};
}}
QLabel[role="readout"] {{
    font-family: {MONO_FONT};
    color: {p.text_dim};
    font-size: 12px;
}}
QLabel[chip="true"] {{
    background: {p.brand_tint};
    color: {p.text};
    font-family: {MONO_FONT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 9px;
    border-radius: 9px;
}}

/* ---- Cards / panels --------------------------------------------------- */
QFrame[role="card"] {{
    background: {p.surface2};
    border: 1px solid {p.border};
    border-radius: 14px;
}}
QFrame[role="well"] {{
    background: {p.overlay};
    border: 1px solid {p.border};
    border-radius: 10px;
}}

/* ---- Buttons ----------------------------------------------------------- */
QPushButton {{
    background: {p.surface2};
    border: 1px solid {p.border_strong};
    border-radius: 10px;
    padding: 8px 16px;
    color: {p.text};
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QPushButton:hover {{ border-color: {p.brand_hi}; background: {p.brand_tint}; }}
QPushButton:pressed {{ background: {p.overlay}; }}
QPushButton:disabled {{ color: {p.text_faint}; border-color: {p.border}; }}
QPushButton[variant="primary"] {{
    background: {accent};
    border: 0;
    color: {p.on_accent};
    font-weight: 700;
    padding: 9px 18px;
}}
QPushButton[variant="primary"]:hover {{ background: {grad(p.brand_hi, p.brand_hi)}; }}
QPushButton[variant="primary"]:pressed {{ background: {p.brand}; }}
QPushButton[variant="primary"]:disabled {{
    background: {p.overlay}; color: {p.text_faint};
}}
QPushButton[variant="secure"] {{
    background: transparent; border: 1px solid {p.secure}; color: {p.secure};
}}
QPushButton[variant="secure"]:hover {{ background: {p.secure}; color: {p.on_accent}; }}
QPushButton[variant="danger"] {{
    background: {rgba(p.danger, 26)};
    border: 1px solid {rgba(p.danger, 110)};
    color: {p.danger};
}}
QPushButton[variant="danger"]:hover {{ background: {p.danger}; color: {p.on_accent}; }}

/* ---- Inputs ------------------------------------------------------------ */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {p.surface2};
    border: 1px solid {p.border_strong};
    border-radius: 12px;
    padding: 10px 12px;
    color: {p.text};
    selection-background-color: {p.brand};
    selection-color: {p.on_accent};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {p.brand_hi};
}}

/* ---- Badges / status pills (styled QLabel via [status=...]) ------------ */
QLabel[pill="true"] {{
    font-family: {MONO_FONT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    padding: 3px 10px;
    border-radius: 10px;
    border: 1px solid {p.border_strong};
}}
QLabel[status="secure"] {{ color: {p.secure}; border-color: {rgba(p.secure, 140)}; background: {rgba(p.secure, 22)}; }}
QLabel[status="armed"]  {{ color: {p.amber};  border-color: {rgba(p.amber, 140)}; background: {rgba(p.amber, 22)}; }}
QLabel[status="blocked"]{{ color: {p.danger}; border-color: {rgba(p.danger, 140)}; background: {rgba(p.danger, 22)}; }}
QLabel[status="offline"]{{ color: {p.info};   border-color: {rgba(p.info, 140)}; background: {rgba(p.info, 22)}; }}

/* ---- Scrollbars (thin, quiet) ------------------------------------------ */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {rgba(p.border_strong, 170)}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.brand_hi}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {rgba(p.border_strong, 170)}; border-radius: 5px; min-width: 30px; }}

/* ---- Code / mono readouts ----------------------------------------------- */
QTextEdit#CodeBlock, QPlainTextEdit#Mono, QTextEdit#DiffView {{
    font-family: {MONO_FONT};
    font-size: 12.5px;
    background: {p.overlay};
    border: 1px solid {p.border};
    border-radius: 10px;
}}

/* ---- Chat bubbles (QFrame[bubble=user|assistant]) ------------------------ */
QFrame[bubble="user"] {{
    background: {p.brand_tint};
    border: 1px solid {rgba(p.brand, 60)};
    border-radius: 16px;
}}
QFrame[bubble="assistant"] {{
    background: {p.surface2};
    border: 1px solid {p.border};
    border-radius: 16px;
}}
QFrame[bubble="trace"] {{
    background: {p.overlay};
    border: 1px dashed {p.border_strong};
    border-radius: 12px;
}}

/* ---- Table (audit browser) ------------------------------------------------ */
QTableWidget, QTableView {{
    background: {p.surface2};
    gridline-color: {p.border};
    border: 1px solid {p.border};
    border-radius: 10px;
    font-family: {MONO_FONT};
    font-size: 12px;
}}
QHeaderView::section {{
    background: {p.overlay};
    color: {p.text_dim};
    border: 0;
    border-bottom: 1px solid {p.border_strong};
    padding: 6px 8px;
    font-family: {MONO_FONT};
    letter-spacing: 1px;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {p.brand}; color: {p.on_accent};
}}

/* ---- Progress (context meter) --------------------------------------------- */
QProgressBar {{
    background: {p.overlay};
    border: 0;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: {p.text_dim};
    font-family: {MONO_FONT};
    font-size: 10px;
}}
QProgressBar::chunk {{ background: {grad(p.brand_hi, p.brand, vertical=False)}; border-radius: 5px; }}

QToolTip {{
    background: {p.surface2};
    color: {p.text};
    border: 1px solid {p.brand_hi};
    border-radius: 6px;
    padding: 4px 8px;
}}

/* ---- Combo boxes, menus, checkboxes ---------------------------------------- */
QComboBox {{
    background: {p.surface2};
    border: 1px solid {p.border_strong};
    border-radius: 10px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 600;
}}
QComboBox:hover {{ border-color: {p.brand_hi}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {p.surface2};
    border: 1px solid {p.border_strong};
    border-radius: 8px;
    selection-background-color: {p.brand};
    selection-color: {p.on_accent};
    outline: 0;
}}
QMenu {{
    background: {p.surface2};
    border: 1px solid {p.border_strong};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 18px;
    border-radius: 7px;
    font-size: 13px;
}}
QMenu::item:selected {{ background: {p.brand}; color: {p.on_accent}; }}
QMenu::item:disabled {{ color: {p.text_faint}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {p.border_strong};
    border-radius: 5px;
    background: {p.surface2};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p.brand};
    border-color: {p.brand_hi};
}}
"""
