"""The chat view — streaming, offline, and never blocking the UI thread.

Generation runs on a :class:`GenerationWorker` (a QThread); tokens arrive over a
signal and append to the live assistant bubble, so the window stays responsive
and the Stop button aborts *now* by calling ``engine.cancel()``. Markdown code
fences are detected and rendered as monospaced code blocks with a copy button —
enough polish to feel like the cloud apps, with nothing leaving the machine.
"""
from __future__ import annotations

import re
from typing import Sequence

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QTextEdit, QVBoxLayout,
                               QWidget)

from ...core.i18n import t
from ...core.llm.engine import (Engine, FakeEngine, GenerationConfig, Message,
                                 Role)
from ..theme import Palette
from ..widgets.tactical import ContextMeter, StencilLabel

_CODE_FENCE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)


class GenerationWorker(QThread):
    chunk = Signal(str)
    done = Signal()

    def __init__(self, engine: Engine, messages: Sequence[Message],
                 config: GenerationConfig):
        super().__init__()
        self._engine = engine
        self._messages = list(messages)
        self._config = config

    def run(self) -> None:
        try:
            for piece in self._engine.stream(self._messages, self._config):
                self.chunk.emit(piece)
        finally:
            self.done.emit()

    def stop(self) -> None:
        self._engine.cancel()


class MessageBubble(QFrame):
    """One turn. ``kind`` is 'user' | 'assistant' | 'trace' → drives the QSS."""

    def __init__(self, kind: str, palette: Palette, author: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("bubble", kind)
        self._palette = palette
        if kind != "trace":
            # Soft card shadow (QSS can't do this; the stack's 28px margins
            # give the blur room, so the scroll viewport doesn't clip it).
            from PySide6.QtGui import QColor
            from PySide6.QtWidgets import QGraphicsDropShadowEffect
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(20)
            shadow.setOffset(0, 3)
            shadow.setColor(QColor(0, 0, 0, 42))
            self.setGraphicsEffect(shadow)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 13)
        v.setSpacing(6)
        if author:
            # Author chip + timestamp, like the design: [BASTIONBOX] 8:03 AM
            import time as _t
            hdr = QHBoxLayout()
            hdr.setSpacing(8)
            chip = QLabel(author.upper())
            chip.setProperty("chip", "true")
            when = QLabel(_t.strftime("%H:%M"))
            when.setProperty("role", "readout")
            hdr.addWidget(chip)
            hdr.addWidget(when)
            hdr.addStretch(1)
            v.addLayout(hdr)
        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._body.setTextFormat(Qt.RichText)
        v.addWidget(self._body)
        self._raw = ""

    def append(self, text: str) -> None:
        self._raw += text
        self._body.setText(self._render(self._raw))

    def set_text(self, text: str) -> None:
        self._raw = text
        self._body.setText(self._render(text))

    def refresh_theme(self) -> None:
        """Re-render with the *current* palette after a live theme switch."""
        self._body.setText(self._render(self._raw))

    def _render(self, text: str) -> str:
        # Minimal, safe markdown: code fences → mono block, `code` → inline.
        # The whole text is HTML-escaped ONCE up front; the fence handler must
        # not escape again or code shows literal &amp;lt; instead of <.
        # Colors come from the CURRENT palette, not the one captured at
        # construction — otherwise a dark→light switch left dark code blocks.
        from ..theme import current_palette
        pal = current_palette()

        def repl(m: re.Match) -> str:
            code = m.group(2) or ""
            return (f'<pre style="background:{pal.overlay};'
                    f'border:1px solid {pal.border};padding:8px;'
                    f'font-family:monospace;white-space:pre-wrap;">{code}</pre>')
        safe = text.replace("&", "&amp;").replace("<", "&lt;")
        html = _CODE_FENCE.sub(repl, safe)
        html = re.sub(r"`([^`]+)`",
                      rf'<code style="color:{pal.info};">\1</code>', html)
        return html.replace("\n", "<br>")


class ChatInput(QTextEdit):
    """The message box, accepting dropped files as attachments.

    QTextEdit would otherwise paste a file drop as a ``file:///`` URL string;
    here a drop with local files is routed to the chat's attachment flow and
    everything else (text, rich snippets) pastes as normal.
    """

    files_dropped = Signal(list)

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802 (Qt override)
        return source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:  # noqa: N802 (Qt override)
        paths = [u.toLocalFile() for u in source.urls() if u.isLocalFile()] \
            if source.hasUrls() else []
        if paths:
            self.files_dropped.emit(paths)
            return
        super().insertFromMimeData(source)


class ChatView(QWidget):
    def __init__(self, engine: Engine, palette: Palette, context_window: int = 8192,
                 system_prompt: str = "", agent_engine: Engine | None = None,
                 index=None, embed_engine=None, store=None,
                 command_allowlist=(), command_timeout_s=60.0,
                 command_output_cap=100_000, agent_max_iterations=24, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._context_window = int(context_window)   # grows when a model loads
        self._agent_engine = agent_engine   # emits tool JSON when in agent mode
        self._index = index                 # hybrid index for search_codebase
        self._embed_engine = embed_engine
        self._command_allowlist = tuple(command_allowlist)
        self._command_timeout_s = command_timeout_s
        self._command_output_cap = command_output_cap
        self._agent_max_iterations = int(agent_max_iterations)
        self._store = store                 # encrypted conversation persistence
        self._scope = "__global__"          # workspace key the chat is saved under
        self._conversation_id = None
        self._palette = palette
        self._system = system_prompt or (
            "You are BastionBox, a fully local assistant. Everything stays on "
            "this machine. Be precise and calm.")
        self._history: list[Message] = []
        self._worker: GenerationWorker | None = None
        # Agent mode is off until a workspace is mounted via enable_agent().
        self._jail = None
        self._workspace = None
        self._library = None   # read-only reference library (set_library)
        self._broker = None
        self._audit = None
        self._agent_worker = None
        self._trace = None
        # The agent's notepad (plan + findings) lives per *conversation*, so a
        # follow-up request still sees the plan from the previous task. Reset on
        # new chat / loaded conversation / workspace switch.
        from ...core.tools.base import NoteStore
        self._notes = NoteStore()
        self._ask_user = None   # bridge callable set via enable_agent()
        # Files dropped onto the chat, riding along with the next message.
        self._attachments = []
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header, ordered like the reference design: readouts on the left,
        # grouped controls + the persona picker on the right.
        top = QHBoxLayout()
        top.setContentsMargins(28, 14, 28, 10)
        top.setSpacing(10)   # breathing room so header controls never touch
        self._channel_lbl = StencilLabel("Secure Channel")
        top.addWidget(self._channel_lbl)
        self._meter = ContextMeter(context_window)
        self._meter.setFixedWidth(190)
        top.addWidget(self._meter)
        top.addStretch(1)
        from PySide6.QtWidgets import QComboBox
        self._compact_btn = QPushButton("")
        self._compact_btn.setFixedSize(38, 36)
        self._compact_btn.clicked.connect(self._on_compact)
        self._history_btn = QPushButton("")
        self._history_btn.setFixedSize(38, 36)
        self._history_btn.clicked.connect(self._show_history_menu)
        self._new_btn = QPushButton("NEW")
        self._new_btn.setFixedHeight(36)
        self._new_btn.clicked.connect(self._new_chat)
        self._persona_box = QComboBox()
        self._persona_box.setFixedHeight(36)
        self.reload_personas()
        self._persona_box.currentTextChanged.connect(self._on_persona)
        top.addWidget(self._compact_btn)
        top.addWidget(self._history_btn)
        top.addWidget(self._new_btn)
        top.addWidget(self._persona_box)
        root.addLayout(top)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._container = QWidget()
        self._stack = QVBoxLayout(self._container)
        self._stack.setContentsMargins(28, 8, 28, 8)
        self._stack.setSpacing(12)
        self._stack.addStretch(1)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        self._greeting()

        # Attachment strip: hidden until a file is dropped onto the chat.
        attach_row = QHBoxLayout()
        attach_row.setContentsMargins(28, 0, 28, 0)
        attach_row.setSpacing(8)
        self._attach_bar = QWidget()
        ab = QHBoxLayout(self._attach_bar)
        ab.setContentsMargins(0, 0, 0, 4)
        ab.setSpacing(8)
        self._attach_label = QLabel("")
        self._attach_label.setProperty("role", "readout")
        self._attach_label.setWordWrap(True)
        ab.addWidget(self._attach_label, 1)
        self._attach_clear = QPushButton("")
        self._attach_clear.setFixedHeight(28)
        self._attach_clear.clicked.connect(self._clear_attachments)
        ab.addWidget(self._attach_clear)
        self._attach_bar.hide()
        attach_row.addWidget(self._attach_bar)
        root.addLayout(attach_row)

        bar = QHBoxLayout()
        bar.setContentsMargins(28, 8, 28, 20)
        bar.setSpacing(8)
        self._input = ChatInput()
        self._input.setFixedHeight(74)
        self._input.files_dropped.connect(self._add_attachments)
        bar.addWidget(self._input, 1)
        col = QVBoxLayout()
        col.setSpacing(6)
        self._send = QPushButton("SEND")
        self._send.setProperty("variant", "primary")
        self._send.clicked.connect(self._on_send)
        self._stop = QPushButton("STOP")
        self._stop.setProperty("variant", "danger")
        self._stop.setEnabled(False)
        self._stop.clicked.connect(self._on_stop)
        col.addWidget(self._send)
        col.addWidget(self._stop)
        bar.addLayout(col)
        root.addLayout(bar)
        self._apply_icons()
        self.retranslate()

    # -- helpers ------------------------------------------------------------
    def _apply_icons(self) -> None:
        """(Re)tint the header/footer button icons from the current palette."""
        from PySide6.QtCore import QSize
        from ..icons import icon
        from ..theme import current_palette
        pal = current_palette()
        self._new_btn.setIcon(icon("plus", pal.text_dim, 16))
        for btn, name in ((self._history_btn, "history"),
                          (self._compact_btn, "compress")):
            btn.setIcon(icon(name, pal.text_dim, 18))
            btn.setIconSize(QSize(18, 18))
        self._send.setIcon(icon("send", pal.on_accent, 16))
        self._stop.setIcon(icon("x", pal.danger, 16))

    def retranslate(self) -> None:
        """Re-read every chat-chrome string in the app-wide language."""
        self._channel_lbl.setText(t("chat.secure_channel").upper())
        self._compact_btn.setToolTip(t("chat.compact_tooltip"))
        self._compact_btn.setAccessibleName(t("chat.compact"))
        self._history_btn.setToolTip(t("chat.history_tooltip"))
        self._history_btn.setAccessibleName(t("chat.history_tooltip"))
        self._new_btn.setText(t("chat.new").upper())
        self._new_btn.setToolTip(t("chat.new_tooltip"))
        self._persona_box.setToolTip(t("chat.persona_tooltip"))
        self._input.setPlaceholderText(t("chat.placeholder"))
        self._send.setText(t("chat.send").upper())
        self._stop.setText(t("chat.stop").upper())
        self._attach_clear.setText(t("chat.attach_clear").upper())
        self._attach_bar.setToolTip(t("chat.attach_bar_tooltip"))
        self._meter.retranslate()

    # -- attachments (drag & drop) ------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self._add_attachments(paths)
            event.acceptProposedAction()

    def _add_attachments(self, paths: list) -> None:
        """Extract each dropped file locally and queue it for the next send."""
        from pathlib import Path
        from ...core.docs import attach as _attach
        for raw in paths[:8]:
            p = Path(raw)
            note = MessageBubble("trace", self._palette,
                                 t("chat.chip_attachment"))
            if p.is_dir():
                note.set_text(t("chat.attach_dir", name=p.name))
                self._insert(note)
                continue
            try:
                att = _attach.load_attachment(p)
            except _attach.TooLarge as exc:
                note.set_text(t("chat.attach_too_big", name=p.name,
                                mb=exc.size_mb))
            except _attach.Unsupported:
                note.set_text(t("chat.attach_unsupported", name=p.name))
            except Exception as exc:  # noqa: BLE001 - surfaced, never crashes
                note.set_text(t("chat.attach_failed", name=p.name, error=exc))
            else:
                self._attachments.append(att)
                note.set_text(t("chat.attach_added", name=att.name,
                                kind=att.kind, chars=f"{att.chars:,}"))
                # Outside-the-jail content entering a conversation is exactly
                # what an auditor wants to see: name, size, and fingerprint.
                if self._audit is not None:
                    self._audit.record("attachment", name=att.name,
                                       path=att.path, chars=att.chars,
                                       sha256=att.sha256)
            self._insert(note)
        self._sync_attach_bar()

    def _sync_attach_bar(self) -> None:
        if not self._attachments:
            self._attach_bar.hide()
            return
        self._attach_label.setText("   ".join(
            t("chat.attach_line", name=a.name, chars=f"{a.chars:,}")
            for a in self._attachments))
        self._attach_bar.show()

    def _clear_attachments(self) -> None:
        self._attachments = []
        self._sync_attach_bar()

    def refresh_theme(self) -> None:
        """Repaint every existing bubble with the newly applied palette."""
        from ..icons import pixmap as _pixmap
        from ..theme import current_palette
        # findChildren reaches bubbles inside avatar-row wrappers too.
        for bubble in self._container.findChildren(MessageBubble):
            bubble.refresh_theme()
        for avatar in self._container.findChildren(QLabel, "Avatar"):
            avatar.setPixmap(_pixmap("box", current_palette().brand, 16))
        self._apply_icons()

    def reload_personas(self) -> None:
        """(Re)populate the persona combo: built-ins + the user's custom ones."""
        from ...core.agent import personas as _personas
        current = self._persona_box.currentText()
        names = list(_personas.all_personas(self._store).keys())
        self._persona_box.blockSignals(True)
        self._persona_box.clear()
        self._persona_box.addItems(names)
        if current in names:
            self._persona_box.setCurrentText(current)
        self._persona_box.blockSignals(False)

    def set_library(self, library) -> None:
        """Attach (or clear) the read-only reference library for agent runs."""
        self._library = library
        if library is not None:
            note = MessageBubble("trace", self._palette, t("chat.chip_library"))
            note.set_text(t("chat.library_note", name=library.display_name))
            self._insert(note)

    def _greeting(self) -> None:
        bubble = MessageBubble("assistant", self._palette, "BASTIONBOX")
        bubble.set_text(t("chat.greeting"))
        self._insert(bubble)

    def _insert(self, w: QWidget) -> None:
        # Assistant turns get the small brand-mark avatar beside the card,
        # like the reference design; the wrapper row stays transparent.
        target = w
        if isinstance(w, MessageBubble) and w.property("bubble") == "assistant":
            from ..icons import pixmap as _pixmap
            from ..theme import current_palette
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            avatar = QLabel()
            avatar.setObjectName("Avatar")
            avatar.setFixedSize(30, 30)
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setPixmap(_pixmap("box", current_palette().brand, 16))
            h.addWidget(avatar, 0, Qt.AlignTop)
            h.addWidget(w, 1)
            target = row
        # Insert before the trailing stretch so bubbles stack from the top.
        self._stack.insertWidget(self._stack.count() - 1, target)
        QApplication.processEvents()
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def enable_agent(self, jail, workspace, broker, audit,
                     ask_question=None) -> None:
        """Switch the view into agent mode for a mounted workspace.

        With a workspace present, Send drives the permissioned agent loop (file
        tools + diff approval) instead of plain chat. Call with ``workspace=None``
        to return to chat. ``ask_question`` is the bridge callable the agent's
        ask_user tool uses to pose a clarifying question on the GUI thread.
        """
        self._jail, self._workspace, self._broker, self._audit = \
            jail, workspace, broker, audit
        self._ask_user = ask_question
        # Conversations are scoped per workspace (need-to-know); switching to a
        # workspace starts a fresh conversation under its key.
        self._scope = workspace.key if workspace is not None else "__global__"
        self._conversation_id = None
        self._reset_notes()
        self._clear_attachments()
        mode = MessageBubble("trace", self._palette, t("chat.chip_mode"))
        if workspace is not None:
            perm_key = {"read_only": "perm.read_only", "ask": "perm.ask",
                        "auto_write": "perm.auto"}.get(
                            workspace.permission.value, "perm.ask")
            mode.set_text(t("chat.agent_armed", name=workspace.display_name,
                            perm=t(perm_key)))
        else:
            mode.set_text(t("chat.agent_disarmed"))
        self._insert(mode)

    def set_engine(self, engine: Engine, model_label: str = "") -> bool:
        """Hot-swap the live chat engine (e.g. after loading a real model).

        Refuses while a generation is in flight so a swap can never orphan a
        running worker. When the previous agent engine was the offline demo
        script, the real engine takes over agent runs too — a loaded model
        drives both plain chat and the tool loop. Returns True if swapped.
        """
        if self._worker is not None or self._agent_worker is not None:
            return False
        # If the agent engine was the scripted demo (a FakeEngine distinct from
        # the chat engine), promote the real engine to drive agent runs as well.
        if self._agent_engine is None or self._agent_engine is self._engine \
                or isinstance(self._agent_engine, FakeEngine):
            self._agent_engine = engine
        self._engine = engine
        # Adopt the loaded model's real context window: update the meter and the
        # budget the agent loop and document reads are sized against.
        n_ctx = getattr(getattr(engine, "info", None), "context_length", None)
        if n_ctx:
            self._context_window = int(n_ctx)
            self._meter.set_window(self._context_window)
        note = MessageBubble("trace", self._palette, t("chat.chip_model"))
        label = model_label or getattr(getattr(engine, "info", None), "name", "")
        base = (t("chat.model_loaded", name=label) if label
                else t("chat.model_loaded_generic"))
        if n_ctx:
            base += " " + t("chat.context_is", n=f"{int(n_ctx):,}")
        note.set_text(base)
        self._insert(note)
        return True

    def _on_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text or self._worker is not None or self._agent_worker is not None:
            return
        self._input.clear()
        shown = text
        if self._attachments:
            # The model gets the extracted text, fitted to a slice of the
            # context window; the transcript shows a short 📎 line per file.
            from ...core.docs.attach import render_attachments
            budget = max(8_000, int(self._context_window * 4 * 0.35))
            text = text + "\n\n" + render_attachments(self._attachments, budget)
            shown += "\n" + "\n".join(
                t("chat.attach_line", name=a.name, chars=f"{a.chars:,}")
                for a in self._attachments)
            self._clear_attachments()
        user_bubble = MessageBubble("user", self._palette, t("chat.you"))
        user_bubble.set_text(shown)
        self._insert(user_bubble)

        self._persist("user", text)
        if self._workspace is not None:
            self._run_agent(text)
        else:
            self._run_chat(text)

    # -- personas & compaction ---------------------------------------------
    def _on_persona(self, name: str) -> None:
        from ...core.agent import personas as _personas
        persona = _personas.get(name, self._store)
        self._system = persona.full_prompt
        note = MessageBubble("trace", self._palette, t("chat.chip_persona"))
        key = ("chat.persona_switched_custom" if persona.custom
               else "chat.persona_switched")
        note.set_text(t(key, name=name))
        self._insert(note)

    def _on_compact(self) -> None:
        if self._worker is not None or self._agent_worker is not None:
            return
        from ...core.agent.compaction import compact
        summary, kept = compact(self._history, self._engine, keep_recent=4)
        if not summary.content:
            note = MessageBubble("trace", self._palette, t("chat.compact"))
            note.set_text(t("chat.compact_nothing"))
            self._insert(note)
            return
        # Replace older turns with the marked summary; keep recent verbatim.
        self._history = [summary, *kept]
        marker = MessageBubble("trace", self._palette,
                               t("chat.chip_compacted"))
        marker.set_text(t("chat.compact_marker") + "\n\n" + summary.content)
        self._insert(marker)
        self._meter.set_usage(sum(len(m.content) for m in self._history) // 4)

    # -- persistence --------------------------------------------------------
    def _persist(self, role: str, content: str) -> None:
        if self._store is None or not content.strip():
            return
        if self._conversation_id is None:
            title = (content.strip().splitlines()[0][:48]
                     or t("chat.default_title"))
            self._conversation_id = self._store.create_conversation(self._scope, title)
        self._store.add_message(self._conversation_id, role, content)

    def _reset_notes(self) -> None:
        """Fresh agent notepad — notes are scoped to one conversation."""
        from ...core.tools.base import NoteStore
        self._notes = NoteStore()

    def _new_chat(self) -> None:
        self._conversation_id = None
        self._history.clear()
        self._clear_messages()
        self._reset_notes()
        self._clear_attachments()
        self._greeting()

    def _clear_messages(self) -> None:
        # Remove every bubble but keep the trailing stretch (last item).
        while self._stack.count() > 1:
            item = self._stack.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _show_history_menu(self) -> None:
        from PySide6.QtWidgets import QMenu
        import time as _t
        menu = QMenu(self)
        if self._store is None:
            menu.addAction(t("chat.history_disabled")).setEnabled(False)
        else:
            convs = self._store.list_conversations(self._scope)
            if not convs:
                menu.addAction(t("chat.history_empty")).setEnabled(False)
            for c in convs[:20]:
                when = _t.strftime("%m-%d %H:%M", _t.localtime(c.updated))
                act = menu.addAction(f"{when}  ·  {c.title}")
                act.triggered.connect(lambda _=False, cid=c.id: self._load_conversation(cid))
        menu.exec(self._history_btn.mapToGlobal(self._history_btn.rect().bottomLeft()))

    def _load_conversation(self, conversation_id: int) -> None:
        if self._store is None:
            return
        self._clear_messages()
        self._history.clear()
        self._reset_notes()   # notes are in-memory only; a loaded chat starts clean
        self._clear_attachments()
        self._conversation_id = conversation_id
        for m in self._store.get_messages(conversation_id):
            role = m["role"]
            author = t("chat.you") if role == "user" else "BASTIONBOX"
            bubble = MessageBubble("user" if role == "user" else "assistant",
                                   self._palette, author)
            bubble.set_text(m["content"])
            self._insert(bubble)
            if role in ("user", "assistant"):
                self._history.append(
                    Message(Role.USER if role == "user" else Role.ASSISTANT, m["content"]))

    def _run_chat(self, text: str) -> None:
        self._history.append(Message(Role.USER, text))
        self._assistant = MessageBubble("assistant", self._palette, "BASTIONBOX")
        # Show a pending cue immediately — some local models (e.g. reasoning
        # models) think for several seconds before the first token, and an
        # empty bubble reads as "frozen". Cleared on the first real chunk.
        self._assistant.set_text(t("chat.thinking"))
        self._insert(self._assistant)
        messages = [Message(Role.SYSTEM, self._system), *self._history]
        cfg = GenerationConfig(temperature=0.7, max_tokens=1024)
        self._worker = GenerationWorker(self._engine, messages, cfg)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(self._on_done)
        self._send.setEnabled(False)
        self._stop.setEnabled(True)
        self._acc = ""
        self._worker.start()

    # -- agent mode ---------------------------------------------------------
    def _run_agent(self, text: str) -> None:
        from ...core.agent.loop import AgentLoop
        from ...core.agent.schemas import default_toolbox
        from ...core.tools.base import ToolContext
        from .agent_worker import AgentWorker

        # Size document reads and history trimming to the live model's context:
        # a single read gets ~45% of the window (leaving room for the system
        # prompt and the reply), and the loop keeps the running history under it.
        engine = self._agent_engine or self._engine
        n_ctx = getattr(getattr(engine, "info", None), "context_length", None) \
            or self._context_window
        read_cap = max(8_000, int(n_ctx * 0.45) * 4)   # tokens→chars (~4/token)
        ctx = ToolContext(jail=self._jail, workspace=self._workspace,
                          broker=self._broker, audit=self._audit,
                          index=self._index, embed_engine=self._embed_engine,
                          command_allowlist=self._command_allowlist,
                          command_timeout_s=self._command_timeout_s,
                          command_output_cap=self._command_output_cap,
                          library=self._library, read_char_cap=read_cap,
                          notes=self._notes, ask_user=self._ask_user)
        # The active persona becomes the agent's <role> section, so e.g. the
        # EA Test-Case Writer voice applies while using tools, not just in chat.
        from ...core.agent import personas as _personas
        persona = _personas.get(self._persona_box.currentText(), self._store)
        loop = AgentLoop(engine, ctx, toolbox=default_toolbox(),
                         context_tokens=int(n_ctx),
                         max_iterations=self._agent_max_iterations,
                         role_prompt=persona.full_prompt)
        self._trace = MessageBubble("trace", self._palette,
                                    t("chat.chip_trace"))
        self._insert(self._trace)
        self._trace_text = ""

        # The agent shares the conversation's memory: prior turns (user asks +
        # final answers, chat or agent alike) ride along as history, so "write
        # a summary of what you learned" actually has the learning in context.
        # Without this every agent turn started blank — and a blank model pads
        # documents with placeholder fluff instead of substance.
        history = list(self._history)
        self._history.append(Message(Role.USER, text))
        self._agent_worker = AgentWorker(loop, text, history)
        self._agent_worker.event.connect(self._on_agent_event)
        self._agent_worker.finished_run.connect(self._on_agent_done)
        self._send.setEnabled(False)
        self._stop.setEnabled(True)
        self._agent_worker.start()

    def _on_agent_event(self, ev) -> None:
        from ...core.agent.loop import EventKind
        if ev.kind is EventKind.PROGRESS:
            # Liveness ping: shown as a transient last line, replaced on every
            # ping and dropped when the step's real events land. Without this a
            # multi-minute CPU prefill reads as "the app broke".
            step = ev.meta.get("step", "?")
            chars = ev.meta.get("chars", 0)
            pending = (t("chat.agent_writing", step=step, chars=chars)
                       if chars else t("chat.agent_reading", step=step))
            self._trace.set_text(self._trace_text + pending)
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            return
        if ev.kind is EventKind.TOOL_CALL:
            def _short(v):  # keep the trace to one line per call
                s = str(v).replace("\n", "⏎")
                return s[:48] + ("…" if len(s) > 48 else "")
            compact = ", ".join(f"{k}={_short(v)}" for k, v in ev.args.items())
            self._trace_text += f"▸ {ev.tool}({compact})\n"
            self._trace.set_text(self._trace_text)
        elif ev.kind is EventKind.OBSERVATION:
            first = (ev.text or "").splitlines()[0] if ev.text else ""
            self._trace_text += f"   ↳ {first[:120]}\n"
            self._trace.set_text(self._trace_text)
        elif ev.kind is EventKind.FINAL:
            # Drop the transient "⋯ step N: writing…" line and remember the
            # answer so the next agent turn knows what this one concluded.
            self._trace.set_text(self._trace_text)
            self._history.append(Message(Role.ASSISTANT, ev.text))
            bubble = MessageBubble("assistant", self._palette, "BASTIONBOX")
            bubble.set_text(ev.text)
            self._insert(bubble)
            self._persist("assistant", ev.text)
        elif ev.kind is EventKind.ERROR:
            self._trace_text += f"⚠ {ev.text}\n"
            self._trace.set_text(self._trace_text)
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_agent_done(self) -> None:
        self._agent_worker = None
        self._send.setEnabled(True)
        self._stop.setEnabled(False)
        # Clear any leftover progress line and reflect the conversation's real
        # size in the meter (agent turns count toward context like chat turns).
        if self._trace is not None:
            self._trace.set_text(self._trace_text)
        self._meter.set_usage(sum(len(m.content) for m in self._history) // 4)

    def _on_chunk(self, piece: str) -> None:
        if not self._acc:                     # first token: drop the pending cue
            self._assistant.set_text("")
        self._acc += piece
        self._assistant.append(piece)
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_done(self) -> None:
        if not self._acc:
            # The model produced no visible text (e.g. spent the whole budget
            # reasoning). Say so honestly instead of leaving the pending cue up.
            self._assistant.set_text(t("chat.empty_reply"))
        self._history.append(Message(Role.ASSISTANT, self._acc))
        self._persist("assistant", self._acc)
        self._meter.set_usage(sum(len(m.content) for m in self._history) // 4)
        self._worker = None
        self._send.setEnabled(True)
        self._stop.setEnabled(False)

    def _on_stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        if self._agent_worker is not None:
            (self._agent_engine or self._engine).cancel()
