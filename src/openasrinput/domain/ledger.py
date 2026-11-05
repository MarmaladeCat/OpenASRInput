"""Strict v1 result ledger: revisions, stable finals and complete finalization."""

from dataclasses import dataclass

AUDIO = {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1}
TERMINALS = {"session.finished", "session.cancelled", "session.error"}


class ProtocolError(ValueError):
    pass


@dataclass
class Utterance:
    revision: int
    text: str
    final: bool


class Ledger:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.seq = 0
        self.ready = False
        self.terminal = False
        self.utterances: dict[str, Utterance] = {}

    @property
    def final_count(self):
        return sum(item.final for item in self.utterances.values())

    @property
    def preview(self):
        return "".join(item.text for item in self.utterances.values() if not item.final)

    def accept(self, event: dict) -> bool:
        if event.get("sessionId") != self.session_id or self.terminal:
            return False
        seq = event.get("seq")
        if type(seq) is not int or seq < 1:
            raise ProtocolError("invalid event sequence")
        if seq <= self.seq:
            return False
        if seq != self.seq + 1:
            raise ProtocolError("event sequence gap; audio replay is unsupported")
        kind = event.get("type")
        changed = True
        if kind == "session.ready":
            timeout = event.get("finalizeTimeoutMs")
            if self.ready or event.get("audio") != AUDIO:
                raise ProtocolError("invalid ready/audio negotiation")
            if type(timeout) is not int or timeout <= 0:
                raise ProtocolError("invalid finalization deadline")
            self.ready = True
        elif kind in {"transcript.partial", "transcript.final"}:
            if not self.ready:
                raise ProtocolError("transcript before ready")
            uid, revision, text = (
                event.get("utteranceId"),
                event.get("revision"),
                event.get("text"),
            )
            if not isinstance(uid, str) or not uid or type(revision) is not int or revision < 1:
                raise ProtocolError("invalid utterance identity/revision")
            if not isinstance(text, str):
                raise ProtocolError("invalid transcript text")
            previous = self.utterances.get(uid)
            final = kind == "transcript.final"
            if previous and previous.final:
                if final and text != previous.text:
                    raise ProtocolError("final text was rewritten")
                changed = False
            elif previous and revision <= previous.revision:
                changed = False
            else:
                self.utterances[uid] = Utterance(revision, text, final)
        elif kind in TERMINALS:
            if kind == "session.finished":
                count = event.get("finalCount")
                if not self.ready or type(count) is not int or count != self.final_count:
                    raise ProtocolError("finalCount does not match received finals")
                if self.preview:
                    raise ProtocolError("finished with unresolved preview")
            self.terminal = True
        else:
            raise ProtocolError("unknown v1 event type")
        self.seq = seq
        return changed
