"""BastionBox entry point.

Order matters and is deliberate: the **network guard is installed before any
other import that could open a socket** — before Qt, before anything. Only then
do we build the QApplication, wire the audit log to the guard so any blocked
attempt is permanently recorded, load the theme and language, and show the
command console. This is the load-bearing sequence the whole security story
rests on, so it lives at the very top of ``main`` in plain sight.
"""
from __future__ import annotations

import sys

# --- STEP 1: arm the offline guard FIRST ----------------------------------
# Nothing above this that touches the network; the guard patches sockets before
# Qt or any dependency gets a chance to phone home.
from bastion.core import config
from bastion.core.security.netguard import guard as _guard

if config.NETGUARD_ENABLED:
    _guard.allow_loopback = config.ALLOW_LOOPBACK_OLLAMA
    _guard.install()

# --- STEP 2: everything else ----------------------------------------------
from bastion.core.i18n import Translator                       # noqa: E402
from bastion.core.llm.engine import DemoEngine                 # noqa: E402
from bastion.core.security.audit import AuditLog               # noqa: E402
from bastion.core.security.crypto import (                     # noqa: E402
    Cipher, load_or_create_store_key)


def _build_cipher() -> tuple[Cipher | None, bool]:
    """Resolve the store cipher: passphrase-derived, or DPAPI machine key.

    Returns ``(cipher, encrypted)``. Encryption is ON by default on Windows —
    a per-install random key wrapped by DPAPI needs no passphrase. If no key
    source or provider exists, we return no cipher and the Security panel
    shows UNSEALED rather than silently pretending.
    """
    if not config.ENCRYPT_AT_REST:
        return None, False
    key = load_or_create_store_key(config.DATA_DIR, config.store_passphrase())
    if key is None:
        return None, False
    try:
        return Cipher(key), True
    except Exception:  # noqa: BLE001
        return None, False


def main() -> int:
    config.ensure_data_dirs()

    # Support/self-diagnosis hook (the windowed exe has no console, so results
    # go to a file and the app exits without showing UI):
    #   BASTION_SELFTEST=llama  → can THIS binary import embedded llama.cpp?
    #   BASTION_SELFTEST=gguf   → can it actually load a registered GGUF and
    #                             generate? (the real end-to-end path)
    import os
    _selftest = os.environ.get("BASTION_SELFTEST")
    if _selftest == "llama":
        out = config.DATA_DIR / "selftest-llama.txt"
        try:
            import llama_cpp
            out.write_text(f"OK {llama_cpp.__version__}", encoding="utf-8")
            return 0
        except Exception:  # noqa: BLE001 - the whole point is capturing it
            import traceback
            out.write_text("FAILED\n" + traceback.format_exc(), encoding="utf-8")
            return 1
    if _selftest == "gguf":
        out = config.DATA_DIR / "selftest-gguf.txt"
        try:
            import time
            from bastion.core.llm.registry import ModelRegistry
            from bastion.core.llm.llama_backend import LlamaBackend
            from bastion.core.llm.engine import Message, Role, GenerationConfig
            reg = ModelRegistry(config.MODELS_DIR / "registry.json")
            models = reg.list_chat_models()
            if not models:
                out.write_text("NO MODELS REGISTERED", encoding="utf-8")
                return 1
            m = models[0]
            t0 = time.time()
            be = LlamaBackend(m, n_ctx=2048)
            be.load()
            load_s = time.time() - t0
            t0 = time.time()
            text = "".join(be.stream(
                [Message(Role.USER, "Say: FROZEN GGUF OK /no_think")],
                GenerationConfig(max_tokens=48, temperature=0.1)))
            out.write_text(
                f"OK model={m.name} load={load_s:.1f}s gen={time.time()-t0:.1f}s "
                f"reply={text!r}", encoding="utf-8")
            return 0
        except Exception:  # noqa: BLE001
            import traceback
            out.write_text("FAILED\n" + traceback.format_exc(), encoding="utf-8")
            return 1

    from PySide6.QtWidgets import QApplication          # imported after the guard
    from PySide6.QtGui import QFont
    from bastion.ui.main_window import MainWindow
    from bastion.ui.theme import THEMES, build_qss

    audit = AuditLog(config.AUDIT_PATH) if config.AUDIT_ENABLED else AuditLog(
        config.DATA_DIR / "audit.jsonl")
    # Wire the guard's block callback to the audit log — a leak attempt is
    # recorded forever, not just counted.
    _guard.on_block = lambda host, port, api: audit.log_network_block(host, port, api)

    cfg = config.RuntimeConfig()
    _cipher, encrypted = _build_cipher()

    from bastion.core.store.db import Store
    store = Store(config.STORE_PATH, cipher=_cipher)

    # Language: the persisted choice wins over the env default; the shared
    # translator is set before any widget reads a string.
    from bastion.core import i18n
    saved_lang = store.get_setting("__global__", "language", cfg.language)
    if saved_lang in i18n.AVAILABLE_LANGUAGES:
        cfg.language = saved_lang
    i18n.set_language(cfg.language)
    tr = Translator(cfg.language)

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    # Load any bundled tactical fonts (optional; falls back to system faces).
    from PySide6.QtGui import QFontDatabase
    fonts_dir = config.resource_path("fonts")
    if fonts_dir.is_dir():
        for ttf in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(ttf))

    # Theme: apply live and let the user pick at launch (until they opt out).
    from bastion.ui.theme import qpalette, set_current_palette
    from bastion.ui import winchrome
    from bastion.ui.transition import crossfade

    # Native title bars follow the palette (fixes the dark "black box" caption
    # over a light app). The styler catches every window as it appears.
    winchrome.install(app)

    def _apply_now(name: str) -> None:
        pal = THEMES.get(name, THEMES["dark"])
        set_current_palette(pal)   # inline-styled widgets read this at render
        # The QPalette colors every UNstyled surface (scroll viewports, bare
        # dialogs) so nothing falls back to the OS dark palette — the real fix
        # for the black boxes behind the chat and the theme picker.
        app.setPalette(qpalette(pal))
        app.setStyleSheet(build_qss(pal))
        winchrome.restyle_all_windows(pal)

    def apply_theme(name: str) -> None:
        # Cross-fade the swap so dark↔light is gradual, not a hard cut. With no
        # windows visible yet (startup) this applies instantly.
        crossfade(app, lambda: _apply_now(name),
                  duration=0 if cfg.reduced_motion else 260)

    from bastion.ui.theme_picker import ThemePicker
    apply_theme(cfg.theme)
    theme_name = ThemePicker.run_if_needed(store, apply_theme, cfg.theme)
    cfg.theme = theme_name
    palette = THEMES.get(theme_name, THEMES["dark"])

    engine = DemoEngine()
    engine.load()

    window = MainWindow(engine, palette, _guard, audit, cfg, tr, encrypted,
                        store=store, apply_theme=apply_theme)
    window.setWindowTitle(f"{config.APP_NAME} — {i18n.t('app.tagline')}")
    window.resize(1180, 780)
    window.show()

    # First-run onboarding: a short, honest tour of the security model.
    from bastion.ui.onboarding import Onboarding
    Onboarding.maybe_show(palette, store, window)

    # --- PC integration (M4): tray residence + global quick-ask palette ---
    from bastion.ui.palette.quick_ask import QuickAskPalette
    from bastion.integrations.hotkey import GlobalHotkey
    from bastion.integrations.tray import Tray
    from PySide6.QtWidgets import QSystemTrayIcon

    quick = QuickAskPalette(engine, palette)

    def _show_window():
        window.showNormal(); window.raise_(); window.activateWindow()

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        # Live in the tray: closing the window keeps the app resident.
        app.setQuitOnLastWindowClosed(False)
        tray = Tray(palette, on_show=_show_window,
                    on_quick_ask=quick.summon, on_quit=app.quit)
        tray.set_status(i18n.t(
            "tray.sealed",
            name=engine.info.name if engine.info else i18n.t("status.no_model")))
        tray.show()
        # Let the window update the tray label when a real model is loaded.
        window._tray = tray

    hotkey = GlobalHotkey(quick.summon)
    if hotkey.install(app):
        audit.record("hotkey_registered", chord=hotkey.chord)

    audit.record("app_start", version=config.VERSION,
                 netguard=config.NETGUARD_ENABLED, air_gap=config.AIR_GAP_BUILD,
                 tray=tray is not None)
    try:
        return app.exec()
    finally:
        hotkey.uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
