"""Pure key arbitration model. A native adapter must provide ordered host replay."""

from dataclasses import dataclass

SHIFTS = frozenset({"Shift_L", "Shift_R"})
ALTS = frozenset({"Alt_L", "Alt_R"})


@dataclass(frozen=True)
class KeyEvent:
    key: str
    pressed: bool
    modifiers: frozenset[str] = frozenset()
    repeat: bool = False
    replayed: bool = False


@dataclass(frozen=True)
class Decision:
    forward: tuple[KeyEvent, ...] = ()
    toggle: bool = False


class ChordGuard:
    def __init__(self):
        self.pending: list[KeyEvent] = []
        self.down: set[str] = set()
        self.suppressed: set[str] = set()
        self.space_down = False
        self.forwarded: set[str] = set()
        self.presses: dict[str, KeyEvent] = {}
        self.blocked = False
        self.z_down = False

    def _flush(self):
        events = tuple(self.pending)
        self.forwarded.update(event.key for event in events)
        self.pending.clear()
        return events

    def reset(self) -> Decision:
        """Flush undecided Shift to the OLD context before detaching the adapter.

        Suppressed key releases remain consumed until physically released, so a
        completed chord never leaks an orphan release into the next context.
        """
        self.blocked = bool(self.down or self.space_down or self.z_down)
        return Decision(self._flush())

    def handle(self, event: KeyEvent) -> Decision:
        if event.replayed:
            return Decision((event,))
        key = event.key
        if key.lower() == "z":
            if self.z_down:
                if not event.pressed:
                    self.z_down = False
                return Decision()
            if (
                event.pressed
                and not event.repeat
                and not self.blocked
                and not self.forwarded
                and self.down & ALTS
                and event.modifiers == frozenset({"Alt"})
            ):
                self.pending.clear()
                self.suppressed.update(self.down)
                self.z_down = True
                return Decision(toggle=True)
        if key in SHIFTS | ALTS:
            if event.pressed:
                if key in self.suppressed:
                    return Decision()
                if event.repeat or key in self.down:
                    return Decision((event,)) if key in self.forwarded else Decision()
                self.down.add(key)
                self.presses[key] = event
                if self.space_down or self.z_down:
                    self.suppressed.add(key)
                elif self.forwarded or event.modifiers - ({"Shift"} if key in SHIFTS else {"Alt"}):
                    self.forwarded.add(key)
                    return Decision(self._flush() + (event,))
                else:
                    self.pending.append(event)
                return Decision()
            self.down.discard(key)
            self.presses.pop(key, None)
            if not self.down and not self.space_down and not self.z_down:
                self.blocked = False
            if key in self.suppressed:
                self.suppressed.discard(key)
                return Decision()
            forwarded = self._flush()
            self.forwarded.discard(key)
            return Decision(forwarded + (event,))
        if key == "Space" and self.space_down:
            if not event.pressed:
                self.space_down = False
                if not self.down:
                    self.blocked = False
            return Decision()
        if (
            key == "Space"
            and event.pressed
            and not event.repeat
            and event.modifiers == frozenset({"Shift"})
            and self.down & SHIFTS
            and not self.forwarded
            and not self.blocked
        ):
            self.pending.clear()
            self.suppressed.update(self.down)
            self.space_down = True
            return Decision(toggle=True)
        # A normal key after a voice chord while Shift is still held must regain
        # its Shift-down before the key, rather than receiving an orphan release.
        restored = tuple(self.presses[key] for key in self.presses if key in self.suppressed)
        self.forwarded.update(self.suppressed)
        self.suppressed.clear()
        return Decision(self._flush() + restored + (event,))
