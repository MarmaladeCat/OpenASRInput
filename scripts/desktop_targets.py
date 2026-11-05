"""Versioned acceptance axes; upstream limitations are not passing tests."""

import itertools

RELEASES = ("22.04", "24.04", "26.04", "debian13", "kali")
LEGACY_RELEASES = ("18.04", "22.04", "26.04")
UBUNTU20_RELEASES = ("20.04", *RELEASES)
DEFAULT_PROFILE = "desktop-v4"
PROFILES = {
    "desktop-v1": LEGACY_RELEASES,
    "desktop-v2": UBUNTU20_RELEASES,
    "desktop-v3": UBUNTU20_RELEASES,
    "desktop-v4": RELEASES,
}
BASES = {
    **{version: "ubuntu:" + version for version in ("18.04", "20.04", "22.04", "24.04", "26.04")},
    "debian13": "debian:trixie-slim",
    "kali": "kalilinux/kali-rolling",
}
DESKTOPS = ("gnome", "kde", "xfce")
ARCHES = ("amd64", "arm64")
PROTOCOLS = ("x11", "wayland")
FRAMEWORKS = ("ibus", "fcitx4", "fcitx5")


def exclusions(profile, release, desktop, protocol, framework):
    """Known unavailable intersections, independent of package/test verdicts."""
    if profile not in ("desktop-v3", "desktop-v4"):
        return []
    reasons = []
    if release == "kali" and framework == "fcitx4":
        reasons.append(
            dict(code="framework-unavailable", reason="Kali 当前受测软件源不提供 Fcitx4。")
        )
    if desktop == "gnome" and release in ("26.04", "kali") and protocol == "x11":
        reasons.append(
            dict(code="x11-unavailable", reason="该发行版受测 GNOME 50 不提供 X11 桌面会话。")
        )
    if framework == "fcitx4" and protocol == "wayland":
        reasons.append(
            dict(code="fcitx4-wayland", reason="Fcitx4 仅支持 X11/XIM，不支持原生 Wayland。")
        )
    return reasons


def scope(
    profile=DEFAULT_PROFILE,
    *,
    releases=None,
    arches=ARCHES,
    desktops=DESKTOPS,
    protocols=PROTOCOLS,
    frameworks=FRAMEWORKS,
):
    targets, excluded = [], []
    for release, arch, desktop, protocol, framework in itertools.product(
        PROFILES[profile] if releases is None else releases, arches, desktops, protocols, frameworks
    ):
        row = dict(
            release=release,
            architecture=arch,
            desktop=desktop,
            protocol=protocol,
            framework=framework,
        )
        reasons = exclusions(profile, release, desktop, protocol, framework)
        if reasons:
            excluded.append(dict(row, exclusionReasons=reasons))
        else:
            targets.append(row)
    return dict(profile=profile, targets=targets, excluded=excluded)


def image(release, arch, framework):
    distribution = "ubuntu" + release if release[0].isdigit() else release
    return f"openasrinput-desktops:{distribution}-{arch}-{framework}"


def unsupported(release, desktop, protocol, framework):
    if release in ("18.04", "20.04"):
        return (
            "package-unsupported",
            "Current candidate needs glibc >= 2.35; this distribution needs an older-ABI build, not a relabeled deb.",
        )
    if desktop == "gnome" and release == "26.04" and protocol == "x11":
        return "session-unavailable", "GNOME 50 no longer provides an X11 desktop session."
    if desktop == "xfce" and protocol == "wayland":
        return (
            "session-unsupported",
            "No stable default Xfce Wayland session in this acceptance profile.",
        )
    if framework == "fcitx4" and protocol == "wayland":
        return (
            "framework-unsupported",
            "Fcitx4 is X11/XIM only; XWayland is not native Wayland input.",
        )
    return None
