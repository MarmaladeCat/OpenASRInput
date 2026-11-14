# OpenASRInput interfaces and behavior contract

**English** | [简体中文](API.zh-CN.md)

For integrators and bridge developers. Input is a Portal client, not an HTTP recognition service. OpenASRPortal's Recognition and Personal Hotwords API v1 is authoritative for the cross-product protocol. This document defines Input's consumption and local input boundaries.

## Portal connection

Configuration stores a Portal HTTP(S) origin, client ASR key, and optional profileId. Admin passwords, Notes tokens, and cloud-provider keys cannot replace the ASR key. HTTP uses `Authorization: Bearer <ASR_KEY>`, rejects redirects, and requires a same-origin WS path belonging to the created sessionId.

Order: GET `/v1/capabilities` and `/v1/profiles` → POST `/v1/sessions` → connect to returned streamPath with a single-use ticket → wait for `session.ready` → upload PCM and consume events → `audio.end` → await terminal events. Creation includes `purpose:"dictation"`, optional clientRequestId/profileId, and `audio:{encoding:"pcm_s16le",sampleRate:16000,channels:1}`.

Send raw little-endian PCM16, mono, 16 kHz in binary WS messages, without a WAV header. Upload only after ready; stop uploading during finalization but keep receiving finals. After failure create a new session; never automatically replay old audio.

Input negotiates `effectiveSessionLimits` and `recognitionCapabilities` when advertised. Creation and ready must agree on `profileId`, `limits` and `capabilities`. Recording uses the smaller of 295 seconds and `maxRecordingMs`, counting capture startup/pre-ready buffering; ready never resets the clock. The same cumulative PCM budget includes stop-time tails and clips only complete samples as capture reaches the limit. If a newly discovered shorter limit is already exceeded by prebuffered audio, reject the round without uploading it. At the limit stop capture and flush accepted audio before audio.end. Pending audio is bounded to 60 seconds. `readyTimeoutMs` is validated and used, with a 45-second legacy fallback. Cancellation interrupts startup and upload.

Settings retain the recognition snapshot and show preview during recording, incremental text after stopping, recognition after stopping, or unknown timing. Runtime `previewPhase` and `recordingLimitMs` come from the active session. Unknown capabilities never imply live preview; SSE/WS transport and `partialResults` alone are insufficient.

## Results and commits

| Field / event          | Input behavior                                                                                             |
| ---------------------- | ---------------------------------------------------------------------------------------------------------- |
| sessionId / seq        | Reject old sessions; consume increasing sequence numbers, ignore duplicates, treat gaps as protocol errors |
| utteranceId / revision | Update complete replacement text by utterance; older revisions never replace newer ones                    |
| transcript.partial     | Update preedit, not permanently committed text                                                             |
| transcript.final       | Commit each utterance at most once; count empty finals too                                                 |
| session.finished       | Check finalCount; no nonempty unfinalized preview should remain                                            |
| session.cancelled      | Abandon this round, never label cancellation success                                                       |
| session.error          | Retain diagnostic errors; clean up capture and connection                                                  |

Portal guarantees an immutable audio-ordered prefix plus a replaceable tail, including interleaved second-pass results. Input commits each unique public final once; the final may be shorter than its preceding preview, with the rest following under a new ID. It never rolls back native commits to repair upstream ordering.

`finalizeTimeoutMs` sets a one-shot deadline when audio.end is sent after buffered PCM, including a receive call already waiting at that moment. Partials cannot renew it. A WS close without a terminal is not success. retryable permits a new-session attempt, not safe recommit of existing text.

## Local bridge contract

Linux frameworks supply input contexts; the Windows native process uses stdio IPC. `generation` identifies the round; `lease/contextId/focusEpoch` pin the target; `commitId` and ACK identify local commits. These are not Portal fields or a stable third-party network API.

A new bridge must acquire/invalidate targets, update/clear preedit, commit/acknowledge stable text, and clean up at completion. Results from an old generation, lost focus, or changed target must not enter a new window. Never automatically retry an unacknowledged commit against another target. Cancellation cannot retract already committed text.

Shift+Space controls ordinary dictation; Enter finalizes and Esc cancels. Text-command editing defaults to Linux Alt+Z and Windows Alt+X and uses an independent model connection, not a Portal WS control command.

Alt uses selection editing only when nonempty text can be read. No selection or unsupported optional selection reading falls back to ordinary dictation, equivalent to Shift+Space. Focus loss, explicit read-only protection, oversized selections and transport failures remain errors. The target is rechecked after optional provider queries.

For dictation display/commit only, ASCII padding spaces after Chinese `。！？` are removed, including across finals in one round. English word spacing and newlines are retained. The protocol ledger retains raw text for revision/final validation; selected-text model results are not normalized.

## Settings and personal hotwords

The local settings page defaults to loopback port 10088. The local launch credential creates an independent page token via `POST /api/settings/session`; `GET` retrieves that page's unchanged deadline. Protected `/api/` requests verify token, expiry, and origin. `settings.timeoutMinutes` is an integer from 0 to 525600, default 20; 0 disables page expiry. A changed duration saved by that page resets its deadline; ordinary requests and reloads do not. Expired page tokens cannot open or mint another session. The local launcher credential remains valid for the settings service lifetime so the settings command can open a fresh page. This is an internal configuration UI, not remote management or third-party database access. Saves check concurrent configuration versions; refresh before editing after a conflict.

Personal hotwords use Portal `/v1/hotwords`: GET retrieves revision; PATCH changes settings; arrays replace as a whole. On 409 refresh and reconcile. `/v1/hotwords/catalog` and individual dictionary downloads only supply candidates; add words and save the personal list to enable them. The same key shares a list; different keys are isolated.

Configuration and local IPC changes require corresponding [unit, UI, and native checks](testing.md). Do not export internal modules as cross-product libraries.
