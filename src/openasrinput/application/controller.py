"""Capture state and text queue. Effects are executed by a platform/audio adapter.

All methods must run on one dispatcher. Context changes must be delivered before
draining at a safe host event-loop boundary; the bridge revalidates every submit.
"""

import time
from dataclasses import dataclass
from uuid import uuid4

from ..domain.bridge import Bridge, CursorFrame, Lease
from ..domain.ledger import Ledger, ProtocolError
from ..domain.waveform import Waveform


@dataclass
class Submission:
    activity_id: str
    generation: int
    session_id: str
    utterance_id: str
    revision: int
    lease: Lease
    commit_id: str
    text: str
    status: str = "queued"
    reason: str = ""


@dataclass(frozen=True)
class Effect:
    kind: str
    generation: int
    session_id: str | None = None


class Controller:
    def __init__(self, bridge: Bridge, *, clock=time.monotonic):
        self.bridge, self.clock = bridge, clock
        self.state = "idle"
        self.activity_id = str(uuid4())
        self.generation = 0
        self.lease: Lease | None = None
        self.ledger: Ledger | None = None
        self.submissions: list[Submission] = []
        self.residuals: list[dict] = []
        self.effects: list[Effect] = []
        self.blocked_leases: dict[str, str] = {}
        self.resume_requested = False
        self.pause_requested = False
        self.finalize_timeout = 0.0
        self.deadline: float | None = None
        self.recording_deadline: float | None = None
        self.error = ""
        self.waveform = Waveform()
        self.cursor_revision = 0
        self.last_frame: CursorFrame | None = None
        self.notice_shown = False
        self.last_presented_at = float("-inf")
        self.stop_reason = ""
        self.transitions = []
        self.finish_pending = False
        self.mode = "dictation"
        self.selected_text = ""
        self.instruction_parts = []
        self.edit_complete = False

    def trace(self, cause):
        self.transitions.append(
            {"cause": cause, "state": self.state, "generation": self.generation, "at": self.clock()}
        )
        self.transitions = self.transitions[-20:]

    def _emit(self, kind):
        self.effects.append(
            Effect(kind, self.generation, self.ledger.session_id if self.ledger else None)
        )

    def take_effects(self):
        effects, self.effects = self.effects, []
        return effects

    def toggle(self, reason="shortcut", *, command=False):
        self.trace(reason)
        if self.state in {"idle", "paused", "failed"}:
            lease = self.bridge.begin_context()
            if lease is None:
                self.error = "请先聚焦可编辑输入框，并结束当前输入法的候选"
                self.stop_reason = "target-unavailable"
                return
            self.lease = lease
            self.waveform.reset()
            self.cursor_revision = 0
            self.last_frame = None
            self.last_presented_at = float("-inf")
            self.stop_reason = ""
            self.generation += 1
            self.ledger = None
            self.error = ""
            self.notice_shown = False
            self.pause_requested = self.resume_requested = False
            self.deadline = None
            self.recording_deadline = None
            self.state = "connecting"
            self.mode = "dictation"
            self.selected_text = ""
            self.instruction_parts = []
            self.edit_complete = False
            if command:
                try:
                    self.selected_text = self.bridge.selection(lease)
                    if len(self.selected_text) > 16000:
                        raise ValueError("选区超过 16000 字符，请缩小选区")
                    if self.selected_text:
                        self.mode = "edit"
                except (ValueError, RuntimeError, OSError) as error:
                    self.fail(str(error))
                    return
            self._emit("session.create")
        elif self.state == "connecting":
            self.pause_requested = True
            self.stop_reason = reason
            self._emit("audio.stop-flush")
        elif self.state == "listening":
            self._pause(reason)
        elif self.state == "pausing":
            self.resume_requested = self.mode != "edit"

    def bind_session(self, generation: int, session_id: str) -> bool:
        if generation != self.generation or self.state != "connecting" or self.ledger:
            return False
        if not isinstance(session_id, str) or not session_id:
            self.fail("invalid session id")
            return False
        self.ledger = Ledger(session_id)
        return True

    def _pause(self, reason="shortcut"):
        self.stop_reason = reason
        self.state = "pausing"
        self.trace("pause:" + reason)
        self.recording_deadline = None
        self._emit("audio.stop-flush")
        self._emit("audio.end")
        self.deadline = self.clock() + self.finalize_timeout

    def _finish(self):
        if self.mode == "edit" and not self.edit_complete:
            if not self.bridge.valid(self.lease):
                self.fail("输入目标已变化，未修改原文")
                return
            if not "".join(self.instruction_parts).strip():
                self.fail("没有识别到修改指令，未修改原文")
                return
            self.state = "processing"
            self.trace("text.edit")
            self._emit("text.edit")
            return
        self.finish_pending = any(
            item.status == "queued" and item.generation == self.generation
            for item in self.submissions
        )
        if self.finish_pending:
            self.state = "pausing"
            return
        self.state = "paused"
        self.trace("session.finished")
        if self.resume_requested:
            self._clear_cursor()
            self.lease = None
            self.last_frame = None
            self.toggle("resume")

    def apply_edit(self, generation, text):
        if generation != self.generation or self.state != "processing":
            return
        if not self.bridge.valid(self.lease):
            self.fail("输入目标已变化，未修改原文")
            return
        self.edit_complete = True
        self.submissions.append(
            Submission(
                self.activity_id,
                generation,
                self.ledger.session_id,
                "text-edit",
                1,
                self.lease,
                str(uuid4()),
                text,
            )
        )
        self._finish()

    def on_event(self, generation: int, event: dict):
        if generation != self.generation or self.ledger is None:
            return
        if self.state not in {"connecting", "listening", "pausing"}:
            return
        try:
            if not self.ledger.accept(event):
                return
        except ProtocolError as error:
            self.fail(str(error))
            return
        kind = event["type"]
        if kind == "session.ready":
            self.finalize_timeout = event["finalizeTimeoutMs"] / 1000
            if self.pause_requested or not self.bridge.valid(self.lease):
                self._pause(self.stop_reason or "context-lost")
            else:
                self.state = "listening"
                # First release pauses before Portal's documented five-minute cap.
                self.recording_deadline = self.clock() + 295
                self._emit("audio.start")
            self.trace("session.ready")
        elif kind == "transcript.final":
            if self.mode == "edit":
                self.instruction_parts.append(event["text"])
                if sum(map(len, self.instruction_parts)) > 4000:
                    self.fail("修改指令过长，未修改原文")
                return
            self.submissions.append(
                Submission(
                    self.activity_id,
                    self.generation,
                    self.ledger.session_id,
                    event["utteranceId"],
                    event["revision"],
                    self.lease,
                    str(uuid4()),
                    event["text"],
                )
            )
            # No bridge calls from network callbacks. drain() is scheduled by the host.
        elif kind == "session.finished":
            if self.state != "pausing":
                self.stop_reason = "remote-finished"
            self._emit("audio.stop")
            self.deadline = None
            self.recording_deadline = None
            self._finish()
        elif kind == "session.cancelled":
            self._discard_current()
            self._emit("audio.stop")
            self.state = "idle"
            self.deadline = None
            self.recording_deadline = None
        elif kind == "session.error":
            self.fail(event.get("message", "Portal session failed"))

    def drain(self):
        """Run only on the host's safe event-loop boundary, never an audio thread."""
        deferred = set()
        for item in self.submissions:
            if item.status != "queued":
                continue
            if item.lease.lease_id in deferred:
                continue
            if not self.bridge.valid(item.lease):
                item.status, item.reason = "retained", "target changed"
                continue
            if item.lease.lease_id in self.blocked_leases:
                item.status = "retained"
                item.reason = self.blocked_leases[item.lease.lease_id]
                continue
            if not item.text:
                item.status = "submitted"
                continue
            try:
                ack = self.bridge.submit(item.lease, item.commit_id, item.text)
            except Exception:
                ack = "unknown"
            if ack == "deferred":
                deferred.add(item.lease.lease_id)
                continue  # Held modifiers or a confirmed partial batch; retry the same ID.
            if ack == "accepted":
                item.status = "submitted"
            else:
                item.status, item.reason = "retained", ack
                self.blocked_leases[item.lease.lease_id] = ack
                self.fail("文本提交失败: " + (getattr(self.bridge, "last_commit_error", "") or ack))
        if self.finish_pending and self.state == "pausing":
            self._finish()
        self._present_cursor()

    def _present_cursor(self):
        if self.lease is None:
            return
        active = self.state in {"connecting", "listening", "pausing", "processing"}
        self._show_failure_notice()
        if (
            not active
            or not self.bridge.valid(self.lease)
            or self.lease.lease_id in self.blocked_leases
        ):
            if active and self.lease.lease_id in self.blocked_leases:
                self.fail("文本提交失败: " + self.blocked_leases[self.lease.lease_id])
                self._show_failure_notice()
            self._clear_cursor()
            self.last_frame = None
            return
        preview = self.ledger.preview if self.ledger else ""
        if self.mode == "edit":
            preview = "".join(self.instruction_parts) + preview
        frame = CursorFrame(
            "edit-" + self.state if self.mode == "edit" else self.state, preview, self.waveform.bars
        )
        if frame == self.last_frame and self.clock() - self.last_presented_at < 0.25:
            return
        self.cursor_revision += 1
        try:
            result = self.bridge.show_cursor(self.lease, self.cursor_revision, frame)
        except Exception:
            result = "unknown"
        if result == "accepted":
            self.last_frame = frame
            self.last_presented_at = self.clock()
        else:
            self.fail("光标预编辑不可用: " + result)
            self._show_failure_notice()
            self._clear_cursor()

    def _show_failure_notice(self):
        if (
            self.state == "failed"
            and self.error
            and not self.notice_shown
            and self.lease is not None
        ):
            self.notice_shown = True
            try:
                self.bridge.show_notice(self.lease, self.error)
            except Exception:
                pass  # Lost host connection cannot be turned into a text commit.

    def _clear_cursor(self):
        try:
            self.bridge.clear_cursor(self.lease)
        except Exception:
            pass  # Native peer disconnect already clears its owned input panel.

    def on_audio(self, generation: int, pcm: bytes):
        if generation == self.generation and self.state in {"connecting", "listening"}:
            self.waveform.feed(pcm)

    def context_changed(self):
        for item in self.submissions:
            if item.status == "queued" and not self.bridge.valid(item.lease):
                item.status, item.reason = "retained", "target changed"
        if self.lease and not self.bridge.valid(self.lease):
            self.resume_requested = False
            if self.state == "listening":
                self._pause("context-lost")
            elif self.state == "connecting":
                self.pause_requested = True
                self.stop_reason = "context-lost"
                self.trace("context-lost")
                self._emit("audio.stop-flush")
            elif self.state == "processing":
                self.fail("输入目标已变化，未修改原文")

    def _discard_current(self):
        for item in self.submissions:
            if item.generation == self.generation and item.status == "queued":
                item.status = "cancelled"

    def cancel(self):
        self.finish_pending = False
        self.stop_reason = "cancelled"
        self.trace("cancelled")
        if self.state in {"connecting", "listening", "pausing", "processing"}:
            self._emit("audio.stop")
            self._emit("session.cancel")
        self._discard_current()
        self.resume_requested = False
        self.deadline = None
        self.recording_deadline = None
        self.state = "idle"
        self.activity_id = str(uuid4())

    def fail(self, message: str):
        if self.state not in {"connecting", "listening", "pausing", "processing"}:
            return
        self.error = message
        self.finish_pending = False
        self.stop_reason = "error"
        self.trace("error")
        self._emit("audio.stop")
        self._emit("session.cancel")
        if self.ledger and self.ledger.preview:
            self.residuals.append(
                {
                    "generation": self.generation,
                    "sessionId": self.ledger.session_id,
                    "text": self.ledger.preview,
                    "status": "unconfirmed",
                    "reason": message,
                }
            )
        for item in self.submissions:
            if item.generation == self.generation and item.status == "queued":
                item.status, item.reason = "retained", message
        self.state = "failed"
        self.notice_shown = False
        self.resume_requested = False
        self.deadline = None
        self.recording_deadline = None

    def tick(self):
        if (
            self.lease
            and self.state in {"connecting", "listening", "processing"}
            and not self.bridge.valid(self.lease)
        ):
            self.context_changed()
        if self.recording_deadline is not None and self.clock() >= self.recording_deadline:
            self.error = "即将达到录音时限，已自动暂停；按快捷键可恢复"
            self._pause("recording-limit")
        if self.deadline is not None and self.clock() >= self.deadline:
            self.fail("FINALIZATION_TIMEOUT")
