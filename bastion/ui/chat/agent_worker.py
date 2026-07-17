"""AgentWorker — runs the agent loop off the GUI thread, streaming events out.

The loop is a generator of :class:`~bastion.core.agent.loop.AgentEvent`. This
QThread consumes it and re-emits each event as a Qt signal so the ChatView can
render the thinking trace, tool calls, observations, and final answer live —
while diff-approval dialogs happen inline via the :class:`ApprovalBridge` the
loop's broker is wired to.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ...core.agent.loop import AgentEvent, AgentLoop


class AgentWorker(QThread):
    event = Signal(object)   # AgentEvent
    finished_run = Signal()

    def __init__(self, loop: AgentLoop, user_message: str, history=None):
        super().__init__()
        self._loop = loop
        self._message = user_message
        self._history = history or []

    def run(self) -> None:
        try:
            for ev in self._loop.run(self._message, self._history):
                self.event.emit(ev)
        except Exception as exc:  # never let a loop bug kill the thread silently
            self.event.emit(AgentEvent(
                kind=_error_kind(), text=f"agent error: {type(exc).__name__}: {exc}"))
        finally:
            self.finished_run.emit()


def _error_kind():
    from ...core.agent.loop import EventKind
    return EventKind.ERROR
