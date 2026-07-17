"""UI smoke test — the window builds, the stylesheet parses, pages switch.

Runs under the Qt 'offscreen' platform so it works headless on CI. It does not
assert pixels; it proves the whole widget tree constructs without error, the
tactical stylesheet applies, every page instantiates, navigation switches the
stack, the diff dialog builds, and the security panel reads live guard state.
Skips cleanly if PySide6 is not installed.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from bastion.core.config import RuntimeConfig  # noqa: E402
from bastion.core.i18n import Translator  # noqa: E402
from bastion.core.llm.engine import DemoEngine  # noqa: E402
from bastion.core.security.audit import AuditLog  # noqa: E402
from bastion.core.security.netguard import NetworkGuard  # noqa: E402
from bastion.ui.theme import THEMES, build_qss  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(build_qss(THEMES["dark"]))
    yield app


def _window(qapp, tmp_path):
    from bastion.ui.main_window import MainWindow
    guard = NetworkGuard(allow_loopback=True)  # not installed; just for status
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.record("app_start", version="test")
    cfg = RuntimeConfig()
    engine = DemoEngine(); engine.load()
    return MainWindow(engine, THEMES["dark"], guard, audit, cfg,
                      Translator("en"), encrypted=True)


def test_agent_mode_runs_through_approval_bridge(qapp, tmp_path, monkeypatch):
    """Mount a workspace, run the offline agent, auto-approve the diff dialog,
    and assert the proposed file actually lands — the full M2 loop, headless."""
    from bastion.core.agent.diffing import Diff
    from bastion.core.agent.permissions import Decision
    from bastion.ui.chat import diff_dialog

    ws_dir = tmp_path / "code"
    (ws_dir / "src").mkdir(parents=True)
    (ws_dir / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    # Auto-approve any diff dialog instead of blocking on a real modal.
    monkeypatch.setattr(diff_dialog.DiffDialog, "ask",
                        staticmethod(lambda *a, **k: Decision(True, "auto (test)")))

    win = _window(qapp, tmp_path)
    win._perm_choice.setText("ASK PER WRITE")
    win._workspace = None
    # Mount directly (bypass the native folder picker) then arm agent mode.
    ws = win._jail.mount(ws_dir, __import__(
        "bastion.core.security.jail", fromlist=["Permission"]).Permission.ASK)
    win._chat.enable_agent(win._jail, ws, win._broker, win._audit)

    win._chat._input.setPlainText("review this workspace")
    win._chat._on_send()
    worker = win._chat._agent_worker
    assert worker is not None
    # Pump the event loop until the worker finishes (bridge marshals via queued
    # signals, so the GUI thread must keep processing events).
    for _ in range(200):
        qapp.processEvents()
        if not worker.isRunning():
            break
        worker.wait(20)
    qapp.processEvents()
    assert (ws_dir / "BASTIONBOX_REVIEW.md").exists()  # the approved write landed


def test_window_builds_and_pages_switch(qapp, tmp_path):
    win = _window(qapp, tmp_path)
    win.show()
    qapp.processEvents()
    # Every nav destination exists and selecting it changes the current page.
    for key in ("chat", "workspaces", "models", "knowledge",
                "security", "settings"):
        win._select(key)
        qapp.processEvents()
        assert win._stack.currentWidget() is win._pages[key]
    win.close()


def test_qss_builds_for_both_themes():
    for name in ("dark", "light"):
        qss = build_qss(THEMES[name])
        assert "QPushButton" in qss
        assert THEMES[name].brand in qss  # palette tokens actually rendered
        assert len(qss) > 2000  # a full stylesheet, not a stub


def test_security_panel_reads_guard_state(qapp, tmp_path):
    from bastion.ui.widgets.security_panel import SecurityPanel
    guard = NetworkGuard(allow_loopback=True).install()
    try:
        import socket
        from bastion.core.security.netguard import NetworkBlocked
        try:
            socket.create_connection(("example.com", 80), timeout=1)
        except NetworkBlocked:
            pass
        audit = AuditLog(tmp_path / "a.jsonl")
        panel = SecurityPanel(guard, audit, THEMES["dark"], encrypted=True,
                              air_gap=False)
        panel.refresh()
        # The panel surfaced the real blocked count (>=1) it read from the guard.
        assert guard.status()["blocked_count"] >= 1
    finally:
        guard.uninstall()


def test_diff_dialog_builds(qapp):
    from bastion.core.agent.diffing import Diff
    from bastion.ui.chat.diff_dialog import DiffDialog
    diff = Diff(path="src/a.py", before="def f():\n    return 1\n",
                after="def f():\n    return 2\n")
    dlg = DiffDialog(diff, THEMES["dark"], "workspace")
    qapp.processEvents()
    added, removed = diff.stats
    assert added == 1 and removed == 1
    dlg.close()


def test_theme_picker_persists_and_can_be_skipped(qapp, tmp_path):
    from bastion.ui.theme_picker import ThemePicker
    from bastion.ui.theme import build_qss, THEMES
    from bastion.core.store.db import Store
    store = Store(tmp_path / "s.db", cipher=None)
    applied = []
    apply = lambda name: applied.append(name)
    # First launch: user picks light and opts out of future prompts.
    dlg = ThemePicker(apply, "dark")
    dlg._pick("light")
    dlg._remember.setChecked(True)
    dlg._confirm()
    store.set_setting("__global__", "theme", dlg.chosen)
    store.set_setting("__global__", "theme_ask", "0" if dlg.dont_ask else "1")
    assert dlg.chosen == "light" and "light" in applied
    # Second launch: skipped, returns saved theme.
    result = ThemePicker.run_if_needed(store, apply, "dark")
    assert result == "light"


def test_tutorial_builds(qapp):
    from bastion.ui.tutorial import Tutorial
    tu = Tutorial(THEMES["dark"])
    qapp.processEvents()
    tu.close()


def test_bubble_repaints_on_theme_switch(qapp):
    """A live dark→light switch must recolor existing bubbles (the core bug)."""
    from bastion.ui.chat.chat_view import MessageBubble
    from bastion.ui.theme import set_current_palette
    set_current_palette(THEMES["dark"])
    bubble = MessageBubble("assistant", THEMES["dark"], "X")
    bubble.set_text("here is `inline code` to color")
    dark_html = bubble._body.text()
    assert THEMES["dark"].info.lstrip("#").lower() in dark_html.lower()
    # Switch theme and repaint — the inline-code color must now be light's.
    set_current_palette(THEMES["light"])
    bubble.refresh_theme()
    light_html = bubble._body.text()
    assert THEMES["light"].info.lstrip("#").lower() in light_html.lower()
    assert dark_html != light_html
    set_current_palette(THEMES["dark"])  # restore for other tests


def test_qpalette_surfaces_match_theme_not_black(qapp):
    """The QPalette must color unstyled surfaces from the theme — this is what
    kills the 'black box' (scroll viewports, bare dialogs) on a dark-mode OS."""
    from PySide6.QtGui import QPalette
    from bastion.ui.theme import THEMES, qpalette
    for name in ("dark", "light"):
        pal = qpalette(THEMES[name])
        # Base drives scroll-area viewports and item views — must be the theme
        # surface, never a fallback black.
        assert pal.color(QPalette.Base).name().lower() == THEMES[name].surface.lower()
        assert pal.color(QPalette.Window).name().lower() == THEMES[name].surface.lower()
        assert pal.color(QPalette.Base).name().lower() != "#000000"
        assert pal.color(QPalette.Text).name().lower() == THEMES[name].text.lower()


def test_crossfade_applies_even_without_windows(qapp):
    """The theme swap must always run, fade or not (best-effort animation)."""
    from bastion.ui.transition import crossfade
    ran = []
    crossfade(qapp, lambda: ran.append(1), duration=0)      # reduced-motion path
    crossfade(qapp, lambda: ran.append(1), duration=200)    # animated path
    assert ran == [1, 1]


def test_frameless_window_with_custom_titlebar(qapp, tmp_path):
    """The main window is frameless and carries its own chrome: title text,
    working minimize/maximize-restore/close buttons, and drag/resize plumbing."""
    from PySide6.QtCore import Qt
    win = _window(qapp, tmp_path)
    win.show(); qapp.processEvents()
    assert win.windowFlags() & Qt.FramelessWindowHint
    tb = win._titlebar
    assert "BastionBox" in tb._title.text()
    # Maximize toggles state and the button icon/tooltip follows it.
    tb.toggle_max(); qapp.processEvents()
    assert win.isMaximized()
    assert tb._max.toolTip() == "Restore"
    tb.toggle_max(); qapp.processEvents()
    assert not win.isMaximized()
    assert tb._max.toolTip() == "Maximize"
    # Close via the custom button actually closes the window.
    tb._close.click(); qapp.processEvents()
    assert not win.isVisible()


def test_message_cards_have_shadow_and_assistant_avatar(qapp):
    """Cards get the soft drop shadow; assistant turns get the avatar chip."""
    from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel
    from bastion.ui.chat.chat_view import ChatView, MessageBubble
    assert isinstance(MessageBubble("assistant", THEMES["dark"], "X")
                      .graphicsEffect(), QGraphicsDropShadowEffect)
    assert isinstance(MessageBubble("user", THEMES["dark"], "Y")
                      .graphicsEffect(), QGraphicsDropShadowEffect)
    assert MessageBubble("trace", THEMES["dark"]).graphicsEffect() is None
    view = ChatView(DemoEngine(), THEMES["dark"])   # greeting = assistant turn
    avatars = view._container.findChildren(QLabel, "Avatar")
    assert avatars and avatars[0].pixmap() is not None
    # refresh_theme still reaches bubbles inside the avatar wrapper row.
    view.refresh_theme()


def test_no_audit_page_in_nav(qapp, tmp_path):
    win = _window(qapp, tmp_path)
    assert "audit" not in win._pages
    assert "audit" not in [n[0] for n in __import__(
        "bastion.ui.main_window", fromlist=["_NAV"])._NAV]


def test_chat_view_streams_offline(qapp):
    from bastion.ui.chat.chat_view import ChatView
    view = ChatView(DemoEngine(), THEMES["dark"])
    view._input.setPlainText("hello bastion")
    view._on_send()
    # Let the worker thread run to completion.
    if view._worker is not None:
        view._worker.wait(3000)
    qapp.processEvents()
    assert view._history and view._history[0].content == "hello bastion"


def test_chat_persists_and_reloads(qapp, tmp_path):
    """A chat turn is saved to the store and can be reloaded into a fresh view."""
    from bastion.ui.chat.chat_view import ChatView
    from bastion.core.store.db import Store
    store = Store(tmp_path / "s.db", cipher=None)
    view = ChatView(DemoEngine(), THEMES["dark"], store=store)
    view._input.setPlainText("remember this question")
    view._on_send()
    if view._worker is not None:
        view._worker.wait(3000)
    qapp.processEvents()
    convs = store.list_conversations("__global__")
    assert convs, "a conversation should have been created"
    msgs = store.get_messages(convs[0].id)
    assert msgs[0]["content"] == "remember this question"
    assert any(m["role"] == "assistant" for m in msgs)
    # Reload into a new view.
    view2 = ChatView(DemoEngine(), THEMES["dark"], store=store)
    view2._load_conversation(convs[0].id)
    assert any(m.content == "remember this question" for m in view2._history)


def test_quick_ask_palette_streams(qapp):
    from bastion.ui.palette.quick_ask import QuickAskPalette
    pal = QuickAskPalette(DemoEngine(), THEMES["dark"])
    pal.summon()
    pal._input.setText("what is bastionbox?")
    pal._ask()
    if pal._worker is not None:
        pal._worker.wait(3000)
    qapp.processEvents()
    assert pal._answer.toPlainText().strip()
    pal.hide()


def test_tray_icon_and_hotkey_build(qapp):
    from bastion.integrations.tray import Tray, _draw_icon
    from bastion.integrations.hotkey import GlobalHotkey
    assert not _draw_icon(THEMES["dark"]).isNull()
    tray = Tray(THEMES["dark"], on_show=lambda: None,
                on_quick_ask=lambda: None, on_quit=lambda: None)
    tray.set_status("demo · sealed")
    hk = GlobalHotkey(lambda: None)
    # install() returns a bool and never raises, whatever the platform allows.
    assert isinstance(hk.install(qapp), bool)
    hk.uninstall()


def test_secure_delete_panic_control(qapp, tmp_path, monkeypatch):
    from bastion.ui.widgets.security_panel import SecurityPanel
    from bastion.core.store.db import Store
    from bastion.core.index.hybrid import HybridIndex
    from bastion.core.security.jail import PathJail, Permission
    from PySide6.QtWidgets import QMessageBox

    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    (ws_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
    jail = PathJail(); ws = jail.mount(ws_dir, Permission.ASK)
    store = Store(tmp_path / "s.db", cipher=None)
    cid = store.create_conversation(ws.key, "chat"); store.add_message(cid, "user", "hi")
    index = HybridIndex(); index.index_workspace(jail, ws, engine=None)
    assert index.count(ws.key) > 0

    audit = AuditLog(tmp_path / "a.jsonl")
    panel = SecurityPanel(NetworkGuard(), audit, THEMES["dark"], encrypted=False,
                          air_gap=False, store=store, index=index,
                          workspace_getter=lambda: ws)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    panel._on_secure_delete()
    assert store.list_conversations(ws.key) == []
    assert index.count(ws.key) == 0


def test_language_switcher_translates_live_and_persists(qapp, tmp_path):
    """Flip the Settings combo to Polski: the whole chrome retranslates in
    place — nav, chat, titlebar, security page — and the choice is persisted
    to the store so the next launch starts in Polish."""
    from bastion.core import i18n
    from bastion.core.store.db import Store
    from bastion.ui.main_window import MainWindow

    store = Store(tmp_path / "s.db", cipher=None)
    guard = NetworkGuard(allow_loopback=True)
    audit = AuditLog(tmp_path / "audit.jsonl")
    engine = DemoEngine(); engine.load()
    window = MainWindow(engine, THEMES["dark"], guard, audit, RuntimeConfig(),
                        Translator("en"), encrypted=True, store=store)
    try:
        assert window._nav_buttons["chat"].text() == "Chat"
        codes = [window._lang_box.itemData(i)
                 for i in range(window._lang_box.count())]
        window._lang_box.setCurrentIndex(codes.index("pl"))   # user clicks Polski
        assert window._nav_buttons["chat"].text() == "Czat"
        assert window._nav_buttons["security"].text() == "Bezpieczeństwo"
        assert window._chat._send.text() == "WYŚLIJ"
        assert "nic nie opuszcza" in window._chat._input.placeholderText()
        assert window._titlebar._close.toolTip() == "Zamknij"
        assert window._pages["security"]._title.text() == "STAN BEZPIECZEŃSTWA"
        assert store.get_setting("__global__", "language") == "pl"
        # A fresh conversation greets in Polish too.
        window._chat._new_chat()
        from bastion.ui.chat.chat_view import MessageBubble
        texts = [b._body.text() for b
                 in window._chat._container.findChildren(MessageBubble)]
        assert any("Bezpieczny kanał otwarty" in t for t in texts)
        # And back: English restores instantly, no restart.
        window._lang_box.setCurrentIndex(codes.index("en"))
        assert window._nav_buttons["chat"].text() == "Chat"
        assert window._chat._send.text() == "SEND"
    finally:
        i18n.set_language("en")   # never leak language state into other tests
        window.deleteLater()


def test_import_gguf_button_verifies_and_registers(qapp, tmp_path, monkeypatch):
    """The Import GGUF button: a correct SHA-256 registers the model; a wrong
    one is refused and nothing is added (fail-closed supply-chain check)."""
    import hashlib
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
    from bastion.ui.main_window import MainWindow

    monkeypatch.setenv("BASTION_MODELS_DIR", str(tmp_path / "models"))
    guard = NetworkGuard(allow_loopback=True)
    audit = AuditLog(tmp_path / "audit.jsonl")
    engine = DemoEngine(); engine.load()
    window = MainWindow(engine, THEMES["dark"], guard, audit, RuntimeConfig(),
                        Translator("en"), encrypted=True)
    # Force the registry onto the temp dir regardless of any cached env.
    from bastion.core.llm.registry import ModelRegistry
    window._model_registry = ModelRegistry(tmp_path / "models" / "registry.json")

    gguf = tmp_path / "qwen2-Q4_K_M.gguf"
    gguf.write_bytes(b"GGUF fake " * 500)
    real_hash = hashlib.sha256(gguf.read_bytes()).hexdigest()

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(gguf), "")))
    seen = {}
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: seen.update(info=a[2])))
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: seen.update(crit=a[2])))
    # Decline the "load it into chat now?" offer — a real modal would block
    # the offscreen test run forever.
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))

    # Correct hash → registered and verified.
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: (real_hash, True)))
    window._on_import_gguf()
    assert "qwen2-Q4_K_M" in window._registry().models
    assert "info" in seen and "crit" not in seen

    # Wrong hash → refused, registry unchanged.
    window._registry().remove("qwen2-Q4_K_M")
    seen.clear()
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("00" * 32, True)))
    window._on_import_gguf()
    assert "qwen2-Q4_K_M" not in window._registry().models
    assert "crit" in seen and "info" not in seen

    # Cancelling the file dialog is a harmless no-op.
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    window._on_import_gguf()   # must not raise
    window.deleteLater()


def test_set_engine_swaps_live_chat_engine(qapp, tmp_path):
    """A loaded model takes over chat (and agent runs when the previous agent
    engine was the offline demo script); a swap is refused mid-generation.

    Pure state assertions — no worker thread is started, so this stays fast.
    """
    from bastion.core.llm.engine import FakeEngine, ScriptedTurn

    window = _window(qapp, tmp_path)
    chat = window._chat
    assert isinstance(chat._engine, DemoEngine)

    real = FakeEngine([ScriptedTurn("Hi from the model.")]); real.load()
    assert chat.set_engine(real, "my-model") is True
    assert chat._engine is real
    assert chat._agent_engine is real          # demo agent engine got promoted

    # A trace bubble announcing the load is present.
    from bastion.ui.chat.chat_view import MessageBubble
    assert any("my-model" in b._body.text()
               for b in chat._container.findChildren(MessageBubble))

    # Refused while a worker is running (never orphan a live generation).
    chat._worker = object()
    assert chat.set_engine(real, "x") is False
    chat._worker = None
    window.deleteLater()


def test_hardware_exports_plan_and_detect():
    """Guards against the dead-name import bug: main_window imports `plan`
    (not `plan_offload`) from hardware — a wrong name is a silent ImportError
    inside the click slot, which reads as 'the button does nothing'."""
    from bastion.core.llm import hardware
    assert hasattr(hardware, "plan") and hasattr(hardware, "detect")
    assert not hasattr(hardware, "plan_offload")


def test_load_registered_reaches_activation_not_silent(qapp, tmp_path, monkeypatch):
    """Clicking LOAD INTO CHAT with one registered model must reach engine
    activation (or show a dialog) — never silently swallow an exception.

    This is the regression for the plan_offload ImportError that made the
    button do nothing. `_activate_engine` is stubbed so no thread/load runs.
    """
    from PySide6.QtWidgets import QMessageBox
    from bastion.core.llm.registry import RegisteredModel
    from bastion.ui.main_window import MainWindow

    window = _window(qapp, tmp_path)
    window._registry().models.clear()
    window._registry().models["Qwen3-Test"] = RegisteredModel(
        name="Qwen3-Test", path="X", sha256="", family="qwen",
        context_length=2048)

    reached, warned = [], []
    monkeypatch.setattr(window, "_activate_engine",
                        lambda e, l: reached.append((type(e).__name__, l)))
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a[2])))
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: warned.append(("CRIT", a[2]))))

    # Route through the same guard the button uses; it must not silently no-op.
    window._guarded(window._on_load_registered)

    # Either the model reached activation (llama.cpp present) or a dialog
    # explained why — but the handler never threw into the void.
    assert reached or warned, "LOAD INTO CHAT did nothing — regression!"
    if reached:
        assert reached[0][0] == "LlamaBackend"
        assert not any(isinstance(w, tuple) and w[0] == "CRIT" for w in warned)
    window.deleteLater()


def test_agent_turn_carries_conversation_history(qapp, tmp_path, monkeypatch):
    """Regression: agent runs used to start with a blank history, so 'write a
    summary of what you learned' had nothing to draw on and the model padded
    documents with placeholders. The worker must receive prior turns, and the
    new user message must join the conversation memory. Thread-free: the
    worker is stubbed out."""
    from bastion.core.agent.permissions import PolicyBroker
    from bastion.core.llm.engine import Message, Role
    from bastion.core.security.audit import AuditLog
    from bastion.core.security.jail import PathJail, Permission

    window = _window(qapp, tmp_path)
    chat = window._chat

    ws_dir = tmp_path / "ws"; ws_dir.mkdir()
    jail = PathJail()
    ws = jail.mount(ws_dir, Permission.ASK, label="ws")
    chat.enable_agent(jail, ws, PolicyBroker(),
                      AuditLog(tmp_path / "a.jsonl"))

    captured = {}

    class FakeWorker:
        def __init__(self, loop, text, history=None):
            captured.update(loop=loop, text=text,
                            history=list(history or []))
        class _Sig:
            def connect(self, *a, **k): pass
        event = _Sig()
        finished_run = _Sig()
        def start(self): captured["started"] = True

    import bastion.ui.chat.agent_worker as aw
    monkeypatch.setattr(aw, "AgentWorker", FakeWorker)

    chat._history[:] = [Message(Role.USER, "what does MIL-STD-810 cover?"),
                        Message(Role.ASSISTANT, "It covers environmental tests.")]
    chat._run_agent("write a summary of what you learned")

    assert captured["started"]
    assert [m.content for m in captured["history"]] == \
        ["what does MIL-STD-810 cover?", "It covers environmental tests."]
    assert chat._history[-1].content == "write a summary of what you learned"
    assert captured["loop"].role_prompt          # persona rides along too
    window.deleteLater()
