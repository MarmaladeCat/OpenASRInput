# OpenASRInput architecture and design

**English** | [简体中文](architecture.zh-CN.md)

For client developers. See [API](API.md) for network fields and the [user guide](user-guide.md) for installation and operation.

## Layers and dependency direction

`src/openasrinput/entrypoints` assembles CLI, daemon, and settings service. `application` controls recording rounds, shortcuts, targets, and commit order; `domain` holds GUI-independent state machines and recognition ledgers. `adapters` connects Portal and platform input; `infrastructure` handles configuration, processes, audio, and OS differences; `presentation` provides previews, panels, and settings pages.

`src/native/` contains IBus, Fcitx4, Fcitx5, and Windows bridges. The GNOME extension integrates Wayland panels. Bridges and Python controllers belong to Input; Portal must not manipulate desktop focus or send keys.

## One input round

Shortcut → pin target context → create Portal session → upload PCM after ready → partial updates preedit → final enters ledger and commit queue → end upload and await finished → clean up.

Network reception and audio capture run concurrently; local commits return to the host's permitted event loop. `sessionId/seq/utteranceId/revision` prevent reordered/duplicate network results; `generation` separates local rounds; `lease/contextId/focusEpoch` separates targets; `commitId` and ACK constrain local commits. None of these identities substitutes for another.

Old results cannot enter a new editor after focus/target changes. Text with uncertain ACK remains unconfirmed, never blindly resent. Cancellation does not undo stable text already committed. Pausing ends the current session; resuming creates a new one. v1 has no audio resumption.

## Platform design

- Linux frameworks maintain preedit and commits; Fcitx4 is X11-only. Wayland focus, cursor rectangles, and panels depend on desktop protocols, not X11 global-injection assumptions.
- Windows native processes and controllers use restricted IPC. Target-control capabilities determine preview/commit strategy; applications need not behave identically.
- Windows editability is independent of optional UIA value/geometry support. PowerPoint can confirm an active text selection through the native object model of the focused `paneClassDC` (or its focused child); an explicit read-only/password/disabled result still rejects input. Ordinary controls in the PowerPoint process retain their normal backend. Missing UIA text ranges use panel-only preview and verified native selection insertion; ambiguous writes are never replayed. Native window and UIA control identity are rechecked after provider calls, including switches within one window.
- A local service serves settings. Configuration changes do not require restarting the user's desktop. Demo mode uses an in-memory target only.

`InsertionEvidence` isolates value reads, bounded document-text snapshots, and count/caret evidence before and after Windows character insertion. A failing optional provider cannot suppress a working alternative. Without any usable baseline, the character backend fails before writing; after a write, it may repeat read-only confirmation but never resend characters. Continuation checkpoints and per-character authorization recheck focus after UIA calls, which may dispatch focus changes reentrantly.

## Configuration and product boundaries

Input owns devices, appearance, shortcuts, Portal connections, and text-editing connections. Personal hotwords persist through Portal APIs. Connection switching revalidates origin, key, and profile; old callbacks cannot overwrite a new connection.

Input performs no model inference and requires no Notes/Drafts database. Text-command and ordinary ASR connections use separate credentials. See [development](development.md) and [testing](testing.md) for builds/native acceptance.
