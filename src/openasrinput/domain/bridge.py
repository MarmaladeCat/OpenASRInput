"""Local bridge contract and an in-memory host for isolated validation."""

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class Lease:
    lease_id: str
    context_id: str
    focus_epoch: int


@dataclass(frozen=True)
class CursorFrame:
    state: str
    text: str
    waveform: str


class Bridge(Protocol):
    def begin_context(self) -> Lease | None: ...
    def selection(self, lease: Lease) -> str: ...
    def valid(self, lease: Lease) -> bool: ...
    def submit(self, lease: Lease, commit_id: str, text: str) -> str: ...
    def show_cursor(self, lease: Lease, revision: int, frame: CursorFrame) -> str: ...
    def clear_cursor(self, lease: Lease) -> None: ...
    def show_notice(self, lease: Lease, message: str) -> str: ...


class MemoryBridge:
    """No Fcitx, keyboard simulation, clipboard, files or system configuration."""

    def __init__(self):
        self.context_id: str | None = None
        self.focus_epoch = 0
        self.composing = False
        self.can_commit = True
        self.commits: list[tuple[str, str, str]] = []
        self._accepted: dict[str, tuple[Lease, str]] = {}
        self.cursor_frame: CursorFrame | None = None
        self.cursor_lease: Lease | None = None
        self.cursor_revision = 0
        self.cursor_updates: list[CursorFrame] = []
        self._leased: Lease | None = None
        self.panel_settings: dict | None = None
        self.notices: list[str] = []
        self.selected_text = ""
        self.selected_snapshot = None

    def focus(self, context_id: str | None, *, can_commit=True):
        self.focus_epoch += 1
        self.context_id = context_id
        self.composing = False
        self.can_commit = can_commit
        self.cursor_frame = None
        self.cursor_lease = None
        self.cursor_revision = 0
        self._leased = None
        self.selected_snapshot = None

    def begin_context(self):
        if self.context_id is None or not self.can_commit or self.composing:
            return None
        self._leased = Lease(str(uuid4()), self.context_id, self.focus_epoch)
        self.selected_snapshot = None
        return self._leased

    def valid(self, lease):
        return (
            self._leased == lease
            and self.context_id == lease.context_id
            and self.focus_epoch == lease.focus_epoch
        )

    def selection(self, lease):
        if not self.valid(lease):
            raise ValueError("输入目标已变化")
        self.selected_snapshot = self.selected_text or None
        return self.selected_text

    def submit(self, lease, commit_id, text):
        previous = self._accepted.get(commit_id)
        if previous is not None:
            return "accepted" if previous == (lease, text) else "failed"
        if not self.valid(lease):
            return "stale"
        if self.selected_snapshot is not None and self.selected_snapshot != self.selected_text:
            return "stale"
        if not self.can_commit:
            return "unsupported"
        if self.composing:
            return "busy"
        self._accepted[commit_id] = (lease, text)
        self.commits.append((lease.context_id, commit_id, text))
        return "accepted"

    def show_cursor(self, lease, revision, frame):
        if not self.valid(lease):
            return "stale"
        if self.composing:
            return "busy"
        if self.cursor_lease != lease:
            self.cursor_revision = 0
        if revision <= self.cursor_revision:
            return "accepted"
        self.cursor_lease, self.cursor_revision = lease, revision
        self.cursor_frame = frame
        self.cursor_updates.append(frame)
        return "accepted"

    def clear_cursor(self, lease):
        if self._leased == lease:
            self._leased = None
        if self.cursor_lease == lease:
            self.cursor_frame = None
            self.cursor_lease = None
            self.cursor_revision = 0

    def configure_panel(self, settings):
        self.panel_settings = dict(settings)
        return "accepted"

    def configure_keyboard(self, inline_preedit):
        self.keyboard_inline_preedit = inline_preedit
        return "accepted"

    def show_notice(self, lease, message):
        if not self.valid(lease):
            return "stale"
        self.clear_cursor(lease)
        self.notices.append(message)
        return "accepted"
