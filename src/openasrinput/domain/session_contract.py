"""Optional v1 snapshots; missing fields keep legacy behavior, never imply preview."""

from .ledger import ProtocolError


def recording_limit_ms(snapshot):
    limits = snapshot.get("limits", {})
    if not isinstance(limits, dict):
        raise ProtocolError("invalid Portal session limits")
    maximum = limits.get("maxRecordingMs", 300000)
    if type(maximum) is not int or not 0 < maximum <= 300000:
        raise ProtocolError("invalid Portal recording limit")
    return maximum


def preview_phase(snapshot):
    capabilities = snapshot.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ProtocolError("invalid Portal capabilities")
    recognition = capabilities.get("recognition", {})
    preview = recognition.get("preview", {}) if isinstance(recognition, dict) else {}
    phase = preview.get("phase", "unknown") if isinstance(preview, dict) else "unknown"
    return phase if phase in {"none", "during_capture", "after_commit", "after_audio_end"} else "unknown"
