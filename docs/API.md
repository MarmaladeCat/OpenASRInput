# OpenASRInput interfaces and behavior contract

**English** | [简体中文](API.zh-CN.md)

For integrators and bridge developers. Input is a Portal client, not an HTTP recognition service. OpenASRPortal's Recognition and Personal Hotwords API v1 is authoritative for the cross-product protocol. This document defines Input's consumption and local input boundaries.

## Portal connection

Configuration stores a Portal HTTP(S) origin, client ASR key, and optional profileId. Admin passwords, Notes tokens, and cloud-provider keys cannot replace the ASR key. HTTP uses `Authorization: Bearer <ASR_KEY>`, rejects redirects, and requires a same-origin WS path belonging to the created sessionId.

Order: GET `/v1/capabilities` and `/v1/profiles` → POST `/v1/sessions` → connect to returned streamPath with a single-use ticket → wait for `session.ready` → upload PCM and consume events → `audio.end` → await terminal events. Creation includes `purpose:"dictation"`, optional clientRequestId/profileId, and `audio:{encoding:"pcm_s16le",sampleRate:16000,channels:1}`.

Send raw little-endian PCM16, mono, 16 kHz in binary WS messages, without a WAV header. Upload only after ready; stop uploading during finalization but keep receiving finals. After failure create a new session; never automatically replay old audio.

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

`finalizeTimeoutMs` is a one-shot finalization deadline; repeated partials cannot extend it indefinitely. A WS close without a terminal event is not success. retryable permits a new-session attempt, not safe recommit of existing text.

## Local bridge contract

Linux frameworks supply input contexts; the Windows native process uses stdio IPC. `generation` identifies the round; `lease/contextId/focusEpoch` pin the target; `commitId` and ACK identify local commits. These are not Portal fields or a stable third-party network API.

A new bridge must acquire/invalidate targets, update/clear preedit, commit/acknowledge stable text, and clean up at completion. Results from an old generation, lost focus, or changed target must not enter a new window. Never automatically retry an unacknowledged commit against another target. Cancellation cannot retract already committed text.

Shift+Space controls ordinary dictation; Enter finalizes and Esc cancels. Text-command editing defaults to Linux Alt+Z and Windows Alt+X and uses an independent model connection, not a Portal WS control command.

## Settings and personal hotwords

The local settings page defaults to loopback port 10088 and generates a short-lived private token. Protected `/api/` requests verify token and origin. This is an internal configuration UI, not remote management or third-party database access. Saves check concurrent configuration versions; refresh before editing after a conflict.

Personal hotwords use Portal `/v1/hotwords`: GET retrieves revision; PATCH changes settings; arrays replace as a whole. On 409 refresh and reconcile. `/v1/hotwords/catalog` and individual dictionary downloads only supply candidates; add words and save the personal list to enable them. The same key shares a list; different keys are isolated.

Configuration and local IPC changes require corresponding [unit, UI, and native checks](testing.md). Do not export internal modules as cross-product libraries.
