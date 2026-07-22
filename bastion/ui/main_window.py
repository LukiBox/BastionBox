"""The main window — a command console: sidebar, stacked pages, status readout.

Left rail is the mission nav (mono, stenciled, one active indicator). The right
is a stack of pages: the live Chat, plus Workspaces, Models, Knowledge, the
Security posture panel, the Audit trail, and Settings. A persistent bottom strip
shows the loaded model and the SECURE/ARMED status pill.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..core.agent.permissions import PolicyBroker
from ..core.config import RuntimeConfig
from ..core.i18n import AVAILABLE_LANGUAGES, Translator, t
from ..core import i18n as _i18n
from ..core.llm.engine import DemoEngine, Engine, FakeEngine, demo_agent_script
from ..core.llm.hardware import detect, recommend_model_class
from ..core.security.audit import AuditLog
from ..core.security.jail import PathJail, Permission
from ..core.security.netguard import NetworkGuard
from .theme import Palette
from .chat.approval_bridge import ApprovalBridge
from .chat.chat_view import ChatView
from .widgets.security_panel import SecurityPanel
from .widgets.tactical import Card, StatusPill


_NAV = [
    ("chat", "nav.chat", "chat"),
    ("workspaces", "nav.workspaces", "grid"),
    ("models", "nav.models", "cpu"),
    ("knowledge", "nav.knowledge", "book"),
    ("security", "nav.security", "shield"),
    ("settings", "nav.settings", "gear"),
]


class MainWindow(QWidget):
    def __init__(self, engine: Engine, palette: Palette, guard: NetworkGuard,
                 audit: AuditLog, cfg: RuntimeConfig, tr: Translator,
                 encrypted: bool, store=None, apply_theme=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Root")
        self._engine = engine
        self._palette = palette
        self._guard = guard
        self._audit = audit
        self._cfg = cfg
        self._tr = tr
        self._store = store
        self._apply_theme = apply_theme   # callable(name) -> restyle the whole app
        # Live language switching: every translatable string registers a
        # closure here; retranslate() re-runs them all in the new language.
        self._retranslators: list = []

        # Agent plumbing: a jail for mounted workspaces, an approval bridge that
        # marshals diff dialogs to this (GUI) thread, and a tier-aware broker.
        self._jail = PathJail()
        self._bridge = ApprovalBridge(palette, self)
        self._broker = PolicyBroker(ask_write=self._bridge.ask_write,
                                    ask_command=self._bridge.ask_command)
        self._workspace = None
        # An engine that emits tool-call JSON for agent runs. Offline, that's a
        # scripted demo so the whole permissioned flow is visible with no GGUF.
        self._agent_engine = (FakeEngine(demo_agent_script())
                              if isinstance(engine, DemoEngine) else engine)
        # Local hybrid index + a deterministic embedder for the offline build.
        from ..core.index.hybrid import HybridIndex
        self._index = HybridIndex()
        self._embed_engine = FakeEngine() if isinstance(engine, DemoEngine) else engine

        self._library = None   # read-only reference library mount

        # Frameless: the OS caption is replaced by our own TitleBar (drag,
        # double-click max, min/max/close) so the chrome matches the design.
        # Edge resizing is restored natively via WM_NCHITTEST (nativeEvent).
        self.setWindowFlag(Qt.FramelessWindowHint, True)

        from ..core.config import APP_NAME
        from .titlebar import TitleBar
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._titlebar = TitleBar(f"{APP_NAME} — {t('app.tagline')}", self)
        self._bind(lambda: self._titlebar.set_title(
            f"{APP_NAME} — {t('app.tagline')}"))
        outer.addWidget(self._titlebar)

        root = QHBoxLayout()
        # The content canvas floats on the sage gradient with rounded corners
        # (the reference-design look); the sidebar sits directly on the wash.
        root.setContentsMargins(0, 0, 10, 10)
        root.setSpacing(4)
        outer.addLayout(root, 1)
        root.addWidget(self._build_sidebar())

        canvas = QFrame()
        canvas.setObjectName("Canvas")
        right = QVBoxLayout(canvas)
        right.setContentsMargins(2, 2, 2, 2)
        right.setSpacing(0)
        self._stack = QStackedWidget()
        self._chat = ChatView(engine, palette, cfg.context_window,
                              agent_engine=self._agent_engine,
                              index=self._index, embed_engine=self._embed_engine,
                              store=store,
                              command_allowlist=cfg.command_allowlist,
                              agent_max_iterations=cfg.agent_max_iterations)
        self._pages = {
            "chat": self._chat,
            "workspaces": self._workspaces_page(),
            "models": self._models_page(),
            "knowledge": self._knowledge_page(),
            "security": SecurityPanel(guard, audit, palette, encrypted, cfg.air_gap,
                                      store=store, index=self._index,
                                      workspace_getter=lambda: self._workspace),
            "settings": self._settings_page(),
        }
        for key in (n[0] for n in _NAV):
            self._stack.addWidget(self._pages[key])
        right.addWidget(self._stack, 1)
        root.addWidget(canvas, 1)

        self._select("chat")

    # -- language -------------------------------------------------------------
    def _bind(self, fn) -> None:
        """Register a retranslation closure and run it once now."""
        self._retranslators.append(fn)
        fn()

    def retranslate(self) -> None:
        """Re-read every bound string in the newly selected language."""
        for fn in self._retranslators:
            fn()
        self._titlebar.retranslate()
        self._chat.retranslate()
        self._pages["security"].retranslate()

    def _on_language_changed(self, index: int) -> None:
        code = self._lang_box.itemData(index)
        if not code or code == _i18n.current_language():
            return
        _i18n.set_language(code)
        self._cfg.language = code
        self._tr.set_language(code)
        if self._store is not None:
            self._store.set_setting("__global__", "language", code)
        self._audit.record("language_changed", language=code)
        self.retranslate()

    # -- frameless chrome -----------------------------------------------------
    def changeEvent(self, event):  # noqa: N802 (Qt override)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.WindowStateChange and hasattr(self, "_titlebar"):
            self._titlebar.sync_max_icon(self.isMaximized())
        super().changeEvent(event)

    def nativeEvent(self, event_type, message):  # noqa: N802 (Qt override)
        """Restore native edge-resizing on the frameless window (Windows).

        Answers ``WM_NCHITTEST`` for the outer 6px band with the matching
        HTLEFT..HTBOTTOMRIGHT code, so the OS drives the resize (correct
        cursors, snapping, DPI) — the missing piece of any frameless design.
        """
        import sys as _sys
        if _sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084 and not self.isMaximized():  # NCHITTEST
                    x = ctypes.c_int16(msg.lParam & 0xFFFF).value
                    y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
                    rect = wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(
                        wintypes.HWND(int(self.winId())), ctypes.byref(rect))
                    m = max(4, int(round(6 * self.devicePixelRatioF())))
                    left = x < rect.left + m
                    right = x >= rect.right - m
                    top = y < rect.top + m
                    bottom = y >= rect.bottom - m
                    code = ((13 if left else 14 if right else 12) if top else
                            (16 if left else 17 if right else 15) if bottom else
                            (10 if left else 11 if right else 0))
                    if code:
                        return True, code
            except Exception:  # noqa: BLE001 - hit-testing is best-effort
                pass
        return super().nativeEvent(event_type, message)

    # -- sidebar ------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        from PySide6.QtCore import QSize

        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(236)
        v = QVBoxLayout(side)
        v.setContentsMargins(20, 8, 16, 18)   # titlebar already pads the top
        v.setSpacing(6)

        brand = QLabel('<span style="font-weight:800;">BASTION</span>'
                       '<span style="font-weight:300;"> BOX</span>')
        brand.setObjectName("Wordmark")
        brand.setTextFormat(Qt.RichText)
        credit = QLabel()
        self._bind(lambda l=credit: l.setText(t("app.credit")))
        credit.setObjectName("WordmarkTag")
        v.addWidget(brand)
        v.addWidget(credit)
        v.addSpacing(24)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}
        for key, label_key, icon_name in _NAV:
            btn = QPushButton()
            self._bind(lambda b=btn, k=label_key: b.setText(t(k)))
            btn.setObjectName("NavItem")
            btn.setCheckable(True)
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(lambda _=False, k=key: self._select(k))
            self._nav_group.addButton(btn)
            self._nav_buttons[key] = btn
            v.addWidget(btn)
        self._tint_nav_icons()

        v.addStretch(1)
        return side

    def _tint_nav_icons(self) -> None:
        """(Re)build the two-state nav icons from the current palette."""
        from .icons import nav_icon
        from .theme import current_palette
        pal = current_palette()
        for key, _label, icon_name in _NAV:
            self._nav_buttons[key].setIcon(
                nav_icon(icon_name, pal.text_dim, pal.on_accent))
        if hasattr(self, "_titlebar"):
            self._titlebar.refresh_icons()

    def _select(self, key: str) -> None:
        self._nav_buttons[key].setChecked(True)
        self._stack.setCurrentWidget(self._pages[key])
        if key == "security":
            self._pages["security"].refresh()

    # -- simple pages -------------------------------------------------------
    def _page_scaffold(self, title_key: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(16)
        h = QLabel()
        self._bind(lambda l=h, k=title_key: l.setText(t(k)))
        h.setProperty("role", "h1")
        v.addWidget(h)
        return page, v

    def _card(self, title_key: str, well: bool = False) -> Card:
        """A Card whose stenciled title follows the app language."""
        card = Card(t(title_key), well=well)
        self._bind(lambda c=card, k=title_key: c.set_title(t(k)))
        return card

    def _workspaces_page(self) -> QWidget:
        page, v = self._page_scaffold("page.workspaces")
        card = self._card("card.mounted")
        self._ws_status = self._readout("")
        self._bind(self._update_ws_status)
        card.add(self._ws_status)
        row = QHBoxLayout()
        self._perm_idx = 1                      # ASK PER WRITE is the default
        self._perm_choice = QPushButton()
        self._bind(lambda: (
            self._perm_choice.setText(t(self._PERM_CYCLE[self._perm_idx][0])),
            self._perm_choice.setToolTip(t("perm.tooltip"))))
        self._perm_choice.clicked.connect(self._cycle_permission)
        mount = QPushButton()
        self._bind(lambda b=mount: b.setText(t("btn.mount")))
        mount.setProperty("variant", "primary")
        mount.clicked.connect(self._on_mount)
        row.addWidget(self._perm_choice)
        row.addStretch(1)
        row.addWidget(mount)
        card.body().addLayout(row)
        v.addWidget(card)

        tiers = self._card("card.tiers")
        for label_key, desc_key, status in (
            ("perm.read_only", "perm.read_only.desc", "secure"),
            ("perm.ask", "perm.ask.desc", "offline"),
            ("perm.auto", "perm.auto.desc", "armed"),
        ):
            row = QHBoxLayout()
            pill = StatusPill(t(label_key), status)
            lbl = self._readout("")
            self._bind(lambda p=pill, k=label_key, s=status: p.set_status(t(k), s))
            self._bind(lambda l=lbl, k=desc_key: l.setText(t(k)))
            row.addWidget(pill)
            row.addSpacing(12)
            row.addWidget(lbl, 1)
            tiers.body().addLayout(row)
        v.addWidget(tiers)
        v.addStretch(1)
        return page

    def _update_ws_status(self) -> None:
        if self._workspace is None:
            self._ws_status.setText(t("ws.none"))
        else:
            self._ws_status.setText(t("ws.mounted",
                                      path=str(self._workspace.root),
                                      perm=self._workspace.permission.value))

    def _models_page(self) -> QWidget:
        page, v = self._page_scaffold("page.models")
        prof = detect()
        hw = self._card("card.hardware")
        hw.add(self._readout(prof.summary()))
        rec = self._readout("")
        self._bind(lambda l=rec, p=prof: l.setText(
            t("models.recommendation") + recommend_model_class(p)))
        hw.add(rec)
        v.addWidget(hw)

        mgr = self._card("card.registry")
        blurb = self._readout("")
        self._bind(lambda l=blurb: l.setText(t("models.registry_blurb")))
        mgr.add(blurb)
        mrow = QHBoxLayout()
        imp = QPushButton()
        self._bind(lambda b=imp: b.setText(t("btn.import")))
        imp.setProperty("variant", "primary")
        imp.clicked.connect(lambda: self._guarded(self._on_import_gguf))
        self._load_btn = QPushButton()
        self._bind(lambda b=self._load_btn: b.setText(t("models.load_into_chat")))
        self._load_btn.clicked.connect(
            lambda: self._guarded(self._on_load_registered))
        mrow.addWidget(imp)
        mrow.addWidget(self._load_btn)
        mrow.addStretch(1)
        mgr.body().addLayout(mrow)
        self._models_status = self._readout("")
        self._bind(self._update_models_status)
        mgr.add(self._models_status)
        v.addWidget(mgr)

        # Optional loopback Ollama — the working path on machines that already
        # run it (never a remote host; the network guard only allows loopback).
        oll = self._card("card.ollama")
        oll_blurb = self._readout("")
        self._bind(lambda l=oll_blurb: l.setText(t("models.ollama_blurb")))
        oll.add(oll_blurb)
        oll_btn = QPushButton()
        self._bind(lambda b=oll_btn: b.setText(t("models.ollama_btn")))
        oll_btn.setProperty("variant", "primary")
        oll_btn.clicked.connect(lambda: self._guarded(self._on_use_ollama))
        orow = QHBoxLayout()
        orow.addWidget(oll_btn)
        orow.addStretch(1)
        oll.body().addLayout(orow)
        v.addWidget(oll)
        v.addStretch(1)
        return page

    # -- model activation -----------------------------------------------------
    def _guarded(self, fn) -> None:
        """Run a button handler so a bug can never present as "nothing happens".

        Qt swallows exceptions raised inside a slot — the click just silently
        does nothing, which is exactly how a stray ImportError hid here. This
        wrapper surfaces any failure as a dialog (and audits it) instead.
        """
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a handler bug must be visible
            import traceback
            from PySide6.QtWidgets import QMessageBox
            try:
                self._audit.record("ui_handler_error", handler=getattr(
                    fn, "__name__", str(fn)), error=f"{type(exc).__name__}: {exc}")
            except Exception:  # noqa: BLE001
                pass
            QMessageBox.critical(
                self, t("models.load_failed_title"),
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")

    def _activate_engine(self, engine, label: str) -> None:
        """Load *engine* on a worker thread, then hand it to the chat.

        A large GGUF takes tens of seconds to load; doing it on the GUI thread
        would freeze the window into a "(not responding)" state. The demo
        engine keeps answering until the swap actually happens, and a load
        failure surfaces as a dialog — the app is never left dead.
        """
        from PySide6.QtCore import QThread, Signal

        if getattr(self, "_engine_loader", None) is not None:
            return                          # a load is already in flight

        class _Loader(QThread):
            done = Signal(object)           # the exception, or None on success

            def __init__(self, eng, parent):
                super().__init__(parent)
                self._eng = eng

            def run(self):
                try:
                    self._eng.load()
                    self.done.emit(None)
                except Exception as exc:    # noqa: BLE001 - marshal to GUI thread
                    self.done.emit(exc)

        # Unmissable feedback: a busy dialog + the button itself goes LOADING….
        # A 17 GB GGUF read cold from disk can take minutes; a subtle status
        # line is not enough signal that anything is happening.
        from PySide6.QtWidgets import QProgressDialog
        self._models_status.setText(t("models.loading", name=label))
        self._load_btn.setEnabled(False)
        self._load_btn.setText(t("models.loading_btn"))
        progress = QProgressDialog(t("models.loading", name=label), "", 0, 0, self)
        progress.setWindowTitle(t("card.registry"))
        progress.setCancelButton(None)          # a llama.cpp load can't abort
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        self._load_progress = progress
        loader = _Loader(engine, self)
        loader.done.connect(
            lambda exc, e=engine, l=label: self._on_engine_loaded(exc, e, l))
        self._engine_loader = loader
        loader.start()

    def _on_engine_loaded(self, exc, engine, label: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        self._engine_loader = None
        progress = getattr(self, "_load_progress", None)
        if progress is not None:
            progress.close()
            self._load_progress = None
        self._load_btn.setEnabled(True)
        self._load_btn.setText(t("models.load_into_chat"))
        self._update_models_status()
        if exc is not None:
            QMessageBox.warning(self, t("models.load_failed_title"), str(exc))
            return
        if not self._chat.set_engine(engine, label):
            QMessageBox.warning(self, t("models.load_failed_title"),
                                t("models.busy"))
            return
        self._engine = engine
        self._audit.record("model_loaded", model=label,
                           backend=type(engine).__name__)
        # Reflect the live model in the tray, if the app wired one in.
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.set_status(t("tray.sealed", name=label))
        QMessageBox.information(self, t("card.registry"),
                                t("models.loaded_ok", name=label))

    def _on_load_registered(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        names = list(self._registry().models.keys())
        if not names:
            QMessageBox.information(self, t("card.registry"), t("models.no_models"))
            return
        name = names[0]
        if len(names) > 1:
            name, ok = QInputDialog.getItem(self, t("models.pick_title"),
                                            t("models.pick_prompt"), names, 0, False)
            if not ok or not name:
                return
        self._load_gguf_model(self._registry().models[name])

    def _load_gguf_model(self, model) -> None:
        from PySide6.QtWidgets import QMessageBox
        from ..core.llm.hardware import detect, plan
        from ..core.llm.llama_backend import LlamaBackend
        # llama.cpp is optional and not always bundled; if it is missing, the
        # backend's load() raises a clear RuntimeError. Catch the import here
        # too so we can point the user at the Ollama path instead.
        try:
            import llama_cpp  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            # Show the REAL import failure alongside the guidance — a support
            # dialog that hides the cause helps nobody.
            QMessageBox.warning(self, t("models.load_failed_title"),
                                t("models.llama_missing")
                                + f"\n\n[{type(exc).__name__}: {exc}]")
            return
        # Open a generous context so whole documents fit — an 8k window is
        # destroyed by nearly any real .docx. plan() sizes the request down to
        # what this machine's RAM can hold.
        from ..core.config import MODEL_CONTEXT
        want_ctx = max(int(model.context_length or 0), MODEL_CONTEXT)
        try:
            p = plan(detect(), model_size_gb=model.size_gb or 4.0,
                     requested_context=want_ctx)
            backend = LlamaBackend(model, n_ctx=p.context_length,
                                   n_gpu_layers=p.gpu_layers)
        except Exception:  # noqa: BLE001 - planning is best-effort, load anyway
            backend = LlamaBackend(model, n_ctx=want_ctx)
        self._activate_engine(backend, model.name)

    def _on_use_ollama(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from ..core.config import OLLAMA_HOST
        from ..core.llm.ollama_backend import OllamaBackend
        try:
            import ollama
            client = ollama.Client(host=OLLAMA_HOST)
            models = [m["model"] if isinstance(m, dict) else m.model
                      for m in client.list()["models"]]
        except Exception:  # noqa: BLE001 - server down / pkg missing → guide them
            QMessageBox.information(self, t("models.ollama_none_title"),
                                    t("models.ollama_none"))
            return
        if not models:
            QMessageBox.information(self, t("models.ollama_none_title"),
                                    t("models.ollama_none"))
            return
        name, ok = QInputDialog.getItem(self, t("models.ollama_pick_title"),
                                        t("models.ollama_pick_prompt"),
                                        models, 0, False)
        if not ok or not name:
            return
        from ..core.config import MODEL_CONTEXT
        self._activate_engine(
            OllamaBackend(name, host=OLLAMA_HOST, n_ctx=MODEL_CONTEXT), name)

    def _registry(self):
        """Lazily open the on-disk model registry (JSON, no network)."""
        if getattr(self, "_model_registry", None) is None:
            from ..core.config import MODELS_DIR
            from ..core.llm.registry import ModelRegistry
            self._model_registry = ModelRegistry(MODELS_DIR / "registry.json")
        return self._model_registry

    def _update_models_status(self) -> None:
        names = list(self._registry().models.keys())
        self._models_status.setText(
            t("models.registered_list", names=", ".join(names)) if names
            else t("models.no_models"))

    def _on_import_gguf(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            self, t("models.import_dialog"), "", t("models.gguf_filter"))
        if not path:
            return
        # Optional out-of-band SHA-256 for supply-chain verification.
        expected, ok = QInputDialog.getText(
            self, t("models.hash_title"), t("models.hash_prompt"))
        if not ok:
            return
        try:
            model, result = self._registry().register(
                path, expected_sha256=expected.strip() or None)
        except ValueError:
            # register() fails closed on a hash mismatch — refuse loudly.
            self._audit.record("model_import_refused", path=str(path))
            QMessageBox.critical(self, t("models.import_failed_title"),
                                 t("models.hash_mismatch"))
            return
        except Exception as exc:  # noqa: BLE001 - surface any I/O failure honestly
            QMessageBox.warning(self, t("models.import_failed_title"), str(exc))
            return
        self._audit.record("model_import", name=model.name,
                           sha256=model.sha256, verified=bool(expected.strip()))
        self._update_models_status()
        QMessageBox.information(
            self, t("card.registry"),
            t("models.imported_ok", name=model.name, fam=model.family,
              quant=model.quantization or "—", size=model.size_gb,
              verify=result.message))
        # Offer to load it right away — importing is registration, not loading;
        # the chat keeps using the demo engine until a model is activated.
        if not model.is_embedding and QMessageBox.question(
                self, t("models.load_after_import_title"),
                t("models.load_after_import", name=model.name)) \
                == QMessageBox.Yes:
            self._load_gguf_model(model)

    def _knowledge_page(self) -> QWidget:
        page, v = self._page_scaffold("page.knowledge")
        card = self._card("card.retrieval")
        blurb = self._readout("")
        self._bind(lambda l=blurb: l.setText(t("knowledge.blurb")))
        card.add(blurb)
        row = QHBoxLayout()
        build = QPushButton()
        self._bind(lambda b=build: b.setText(t("btn.build_index")))
        build.setProperty("variant", "primary")
        build.clicked.connect(self._on_build_index)
        self._index_stats = None       # set by _on_build_index
        self._index_status = self._readout("")
        self._bind(self._update_index_status)
        row.addWidget(build)
        row.addStretch(1)
        card.body().addLayout(row)
        card.add(self._index_status)
        v.addWidget(card)

        search = self._card("card.search")
        from PySide6.QtWidgets import QLineEdit
        self._kn_query = QLineEdit()
        self._bind(lambda e=self._kn_query: e.setPlaceholderText(
            t("knowledge.search_placeholder")))
        self._kn_query.returnPressed.connect(self._on_knowledge_search)
        search.add(self._kn_query)
        self._kn_results = self._readout("")
        self._kn_results.setObjectName("Mono")
        search.add(self._kn_results)
        v.addWidget(search)

        lib = self._card("card.library")
        self._lib_stats = None         # set by _on_index_library
        self._lib_status = self._readout("")
        self._bind(self._update_lib_status)
        lib.add(self._lib_status)
        lrow = QHBoxLayout()
        attach = QPushButton()
        self._bind(lambda b=attach: b.setText(t("btn.attach_library")))
        attach.setProperty("variant", "primary")
        attach.clicked.connect(self._on_attach_library)
        self._lib_index_btn = QPushButton()
        self._bind(lambda b=self._lib_index_btn: (
            b.setText(t("btn.index_library")),
            b.setToolTip(t("library.index_tooltip"))))
        self._lib_index_btn.setEnabled(False)
        self._lib_index_btn.clicked.connect(self._on_index_library)
        lrow.addWidget(attach)
        lrow.addWidget(self._lib_index_btn)
        lrow.addStretch(1)
        lib.body().addLayout(lrow)
        v.addWidget(lib)
        v.addStretch(1)
        return page

    def _update_index_status(self) -> None:
        if self._index_stats is None:
            self._index_status.setText(t("knowledge.no_index"))
        else:
            self._index_status.setText(t("knowledge.indexed", **self._index_stats))

    def _update_lib_status(self) -> None:
        if self._library is None:
            self._lib_status.setText(t("library.blurb"))
        elif self._lib_stats is None:
            self._lib_status.setText(t("library.attached",
                                       path=str(self._library.root)))
        else:
            self._lib_status.setText(t("library.indexed",
                                       path=str(self._library.root),
                                       **self._lib_stats))

    def _on_attach_library(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        folder = QFileDialog.getExistingDirectory(
            self, t("library.attach_dialog"))
        if not folder:
            return
        try:
            lib = self._jail.mount(
                folder, Permission.READ_ONLY,
                label=folder.replace("\\", "/").rstrip("/").split("/")[-1])
        except Exception as exc:  # noqa: BLE001 - surface jail refusals honestly
            QMessageBox.warning(self, t("library.attach_refused"), str(exc))
            return
        self._library = lib
        self._lib_stats = None
        self._audit.record("library_attach", path=str(lib.root))
        self._update_lib_status()
        self._lib_index_btn.setEnabled(True)
        self._chat.set_library(lib)

    def _on_index_library(self) -> None:
        if self._library is None:
            return
        stats = self._index.index_workspace(self._jail, self._library,
                                            engine=self._embed_engine)
        self._audit.record("library_index", library=self._library.key, **stats)
        self._lib_stats = stats
        self._update_lib_status()

    def _on_build_index(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        if self._workspace is None:
            QMessageBox.information(self, t("ws.no_workspace_title"),
                                    t("ws.no_workspace_msg"))
            return
        stats = self._index.index_workspace(self._jail, self._workspace,
                                            engine=self._embed_engine)
        self._audit.record("index_build", workspace=self._workspace.key, **stats)
        self._index_stats = stats
        self._update_index_status()

    def _on_knowledge_search(self) -> None:
        if self._workspace is None:
            self._kn_results.setText(t("knowledge.mount_first"))
            return
        hits = self._index.search(self._kn_query.text(), self._workspace.key,
                                  engine=self._embed_engine, top_k=6)
        if not hits:
            self._kn_results.setText(t("knowledge.not_found"))
            return
        self._kn_results.setText("\n".join(
            f"[{h.citation}]  {h.chunk.kind} {h.chunk.name}" for h in hits))

    def _settings_page(self) -> QWidget:
        from PySide6.QtWidgets import QComboBox
        page, v = self._page_scaffold("page.settings")
        appearance = self._card("card.appearance")
        self._theme_readout = self._readout("")
        self._bind(self._update_settings_summary)
        appearance.add(self._theme_readout)
        row = QHBoxLayout()
        change = QPushButton()
        self._bind(lambda b=change: b.setText(t("btn.change_theme")))
        change.clicked.connect(self._change_theme)
        # Language picker: English / Polski, applied live and persisted.
        self._lang_box = QComboBox()
        self._lang_box.setFixedHeight(36)
        for code, name in AVAILABLE_LANGUAGES.items():
            self._lang_box.addItem(name, userData=code)
        codes = list(AVAILABLE_LANGUAGES)
        if self._cfg.language in codes:
            self._lang_box.setCurrentIndex(codes.index(self._cfg.language))
        self._lang_box.currentIndexChanged.connect(self._on_language_changed)
        row.addWidget(change)
        row.addWidget(self._lang_box)
        row.addStretch(1)
        appearance.body().addLayout(row)
        v.addWidget(appearance)

        engine = self._card("card.engine")
        eng_lbl = self._readout("")
        self._bind(lambda l=eng_lbl: l.setText(t(
            "settings.engine_summary", backend=self._cfg.engine_backend,
            ctx=f"{self._cfg.context_window:,}", temp=self._cfg.temperature)))
        engine.add(eng_lbl)
        v.addWidget(engine)

        sec = self._card("card.security")
        sec_lbl = self._readout("")
        self._bind(lambda l=sec_lbl: l.setText(t(
            "settings.security_summary",
            ng="ARMED" if self._cfg.netguard_enabled else "OFF",
            enc=self._cfg.encrypt_at_rest, audit=self._cfg.audit_enabled,
            ag=self._cfg.air_gap)))
        sec.add(sec_lbl)
        v.addWidget(sec)

        personas = self._card("card.personas")
        p_blurb = self._readout("")
        self._bind(lambda l=p_blurb: l.setText(t("personas.blurb")))
        personas.add(p_blurb)
        prow = QHBoxLayout()
        new_p = QPushButton()
        self._bind(lambda b=new_p: b.setText(t("btn.new_persona")))
        new_p.setProperty("variant", "primary")
        new_p.clicked.connect(lambda: self._edit_persona(None))
        edit_p = QPushButton()
        self._bind(lambda b=edit_p: b.setText(t("btn.edit_persona")))
        edit_p.clicked.connect(self._pick_persona_to_edit)
        prow.addWidget(new_p)
        prow.addWidget(edit_p)
        prow.addStretch(1)
        personas.body().addLayout(prow)
        self._personas_status = self._readout("")
        self._bind(lambda: self._personas_status.setText(self._personas_summary()))
        personas.add(self._personas_status)
        v.addWidget(personas)

        about = self._card("card.about")
        from ..core.config import VERSION, APP_NAME
        about_lbl = self._readout("")
        self._bind(lambda l=about_lbl: l.setText(
            t("about.blurb", app=APP_NAME, version=VERSION)))
        about.add(about_lbl)
        credit = self._readout("")
        self._bind(lambda l=credit: l.setText(t("about.credit")))
        about.add(credit)
        arow = QHBoxLayout()
        tour = QPushButton()
        self._bind(lambda b=tour: b.setText(t("btn.onboarding")))
        tour.clicked.connect(self._replay_onboarding)
        tut = QPushButton()
        self._bind(lambda b=tut: b.setText(t("btn.tutorial")))
        tut.setProperty("variant", "primary")
        tut.clicked.connect(self._open_tutorial)
        arow.addWidget(tour)
        arow.addWidget(tut)
        arow.addStretch(1)
        about.body().addLayout(arow)
        v.addWidget(about)
        v.addStretch(1)
        return page

    def _update_settings_summary(self) -> None:
        self._theme_readout.setText(t(
            "settings.summary", theme=self._cfg.theme,
            language=AVAILABLE_LANGUAGES.get(self._cfg.language,
                                             self._cfg.language),
            rm=self._cfg.reduced_motion))

    # -- custom personas ------------------------------------------------------
    def _personas_summary(self) -> str:
        from ..core.agent import personas as _personas
        custom = _personas.load_custom(self._store)
        if not custom:
            return t("personas.none")
        return t("personas.custom") + ", ".join(custom.keys())

    def _pick_persona_to_edit(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from ..core.agent import personas as _personas
        custom = _personas.load_custom(self._store)
        if not custom:
            QMessageBox.information(self, t("persona.none_title"),
                                    t("persona.none_msg"))
            return
        name, ok = QInputDialog.getItem(self, t("persona.pick_title"),
                                        t("persona.pick_label"),
                                        list(custom.keys()), 0, False)
        if ok and name:
            self._edit_persona(custom[name])

    def _edit_persona(self, persona) -> None:
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLineEdit,
                                       QPlainTextEdit, QPushButton, QVBoxLayout)
        from ..core.agent import personas as _personas

        dlg = QDialog(self)
        dlg.setWindowTitle(t("persona.dialog_title"))
        dlg.setMinimumSize(560, 420)
        v = QVBoxLayout(dlg)
        v.setSpacing(10)
        name_lbl = QLabel(t("persona.name_label"))
        name_lbl.setProperty("role", "stencil")
        name_edit = QLineEdit(persona.name if persona else "")
        prompt_lbl = QLabel(t("persona.prompt_label"))
        prompt_lbl.setProperty("role", "stencil")
        prompt_edit = QPlainTextEdit(persona.prompt if persona else "")
        prompt_edit.setPlaceholderText(t("persona.prompt_placeholder"))
        v.addWidget(name_lbl); v.addWidget(name_edit)
        v.addWidget(prompt_lbl); v.addWidget(prompt_edit, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        if persona is not None:
            delete = QPushButton(t("persona.delete"))
            delete.setProperty("variant", "danger")
            buttons.addButton(delete, QDialogButtonBox.DestructiveRole)
            delete.clicked.connect(lambda: dlg.done(2))
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)

        result = dlg.exec()
        custom = _personas.load_custom(self._store)
        if result == 2 and persona is not None:                    # delete
            custom.pop(persona.name, None)
        elif result == QDialog.Accepted:                            # save
            name = name_edit.text().strip()
            prompt = prompt_edit.toPlainText().strip()
            if not name or not prompt:
                return
            if persona is not None and persona.name != name:
                custom.pop(persona.name, None)   # renamed: drop the old key
            custom[name] = _personas.Persona(name, prompt, custom=True)
        else:
            return
        if self._store is not None:
            _personas.save_custom(self._store, custom)
            self._audit.record("personas_updated", count=len(custom))
        self._personas_status.setText(self._personas_summary())
        self._chat.reload_personas()

    def _replay_onboarding(self) -> None:
        from .onboarding import Onboarding
        Onboarding(self._palette, self).exec()

    def _open_tutorial(self) -> None:
        from .tutorial import Tutorial
        Tutorial(self._palette, self).exec()

    def _change_theme(self) -> None:
        from .theme_picker import ThemePicker
        from .theme import THEMES
        apply = self._apply_theme or (lambda name: None)
        dlg = ThemePicker(apply, self._cfg.theme, self)
        if dlg.exec():
            self._cfg.theme = dlg.chosen
            self._palette = THEMES.get(dlg.chosen, THEMES["dark"])
            if self._store is not None:
                self._store.set_setting("__global__", "theme", dlg.chosen)
            self._update_settings_summary()
        else:
            apply(self._cfg.theme)  # revert live preview if cancelled
        # Repaint inline-styled chat content (code blocks, traces) so existing
        # bubbles pick up the new palette instead of keeping the old colors —
        # and re-tint icons + the native title bar to match.
        self._chat.refresh_theme()
        self._tint_nav_icons()
        from .winchrome import restyle_all_windows
        restyle_all_windows()

    def _readout(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", "readout")
        lbl.setWordWrap(True)
        return lbl

    # -- workspace mounting -------------------------------------------------
    # (label translation key, permission) — selection is tracked by index in
    # self._perm_idx so it survives live language switches.
    _PERM_CYCLE = [
        ("perm.read_only", Permission.READ_ONLY),
        ("perm.ask", Permission.ASK),
        ("perm.auto", Permission.AUTO_WRITE),
    ]

    def _cycle_permission(self) -> None:
        self._perm_idx = (self._perm_idx + 1) % len(self._PERM_CYCLE)
        self._perm_choice.setText(t(self._PERM_CYCLE[self._perm_idx][0]))

    def _selected_permission(self) -> Permission:
        return self._PERM_CYCLE[self._perm_idx][1]

    def _on_mount(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        folder = QFileDialog.getExistingDirectory(self, t("ws.mount_dialog"))
        if not folder:
            return
        try:
            ws = self._jail.mount(folder, self._selected_permission(),
                                  label=folder.replace("\\", "/").rstrip("/").split("/")[-1])
        except Exception as exc:  # noqa: BLE001 - surface jail refusals honestly
            QMessageBox.warning(self, t("ws.mount_refused"), str(exc))
            return
        self._workspace = ws
        self._audit.record("workspace_mount", path=str(ws.root),
                           permission=ws.permission.value)
        self._update_ws_status()
        # Arm the chat's agent mode and jump the operator to it.
        self._chat.enable_agent(self._jail, ws, self._broker, self._audit,
                                ask_question=self._bridge.ask_question)
        self._select("chat")
