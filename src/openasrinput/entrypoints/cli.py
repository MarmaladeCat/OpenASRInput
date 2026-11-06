"""Offline demo; the default entry point never opens a device or network socket."""

import argparse
import json
import os
import sys

from .. import __version__


def demo():
    import struct

    from ..application.controller import Controller
    from ..domain.bridge import MemoryBridge
    from ..domain.chord import ChordGuard, KeyEvent
    from ..domain.ledger import AUDIO

    host = MemoryBridge()
    host.focus("demo-input")
    controller = Controller(host)
    chord = ChordGuard()
    chord.handle(KeyEvent("Shift_L", True))
    decision = chord.handle(KeyEvent("Space", True, frozenset({"Shift"})))
    if decision.toggle:
        controller.toggle()
    controller.take_effects()
    generation = controller.generation
    controller.bind_session(generation, "offline-session")
    controller.on_event(
        generation,
        {
            "type": "session.ready",
            "sessionId": "offline-session",
            "seq": 1,
            "audio": AUDIO,
            "finalizeTimeoutMs": 2000,
        },
    )
    controller.on_audio(generation, struct.pack("<320h", *([16000] * 320)))
    controller.on_event(
        generation,
        {
            "type": "transcript.partial",
            "sessionId": "offline-session",
            "seq": 2,
            "utteranceId": "sentence-1",
            "revision": 1,
            "text": "可修订预览",
        },
    )
    controller.drain()
    first_preview = host.cursor_frame.text
    controller.on_event(
        generation,
        {
            "type": "transcript.partial",
            "sessionId": "offline-session",
            "seq": 3,
            "utteranceId": "sentence-1",
            "revision": 2,
            "text": "语音与光标预编辑。",
        },
    )
    controller.drain()
    revised_preview = host.cursor_frame.text
    wave = host.cursor_frame.waveform
    controller.on_event(
        generation,
        {
            "type": "transcript.final",
            "sessionId": "offline-session",
            "seq": 4,
            "utteranceId": "sentence-1",
            "revision": 3,
            "text": "语音与光标预编辑。",
        },
    )
    controller.drain()
    controller.toggle()
    controller.on_event(
        generation,
        {
            "type": "session.finished",
            "sessionId": "offline-session",
            "seq": 5,
            "finalCount": 1,
        },
    )
    print(
        json.dumps(
            {
                "mode": "offline-memory-host",
                "hotkeyToggle": decision.toggle,
                "firstPreview": first_preview,
                "revisedPreview": revised_preview,
                "waveform": wave,
                "state": controller.state,
                "submitted": [text for _, _, text in host.commits],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


async def run_daemon(store, socket_path, overrides):
    import asyncio

    from ..adapters.host import bridge_for_platform
    from ..application.daemon import Daemon
    from ..application.runtime import ConfigRuntime

    bridge = bridge_for_platform(socket_path)
    runtime = None
    try:
        runtime = ConfigRuntime(store, bridge, overrides=overrides)

        async def tick(coordinator):
            if getattr(bridge, "quit_requested", False):
                raise asyncio.CancelledError()
            await runtime.tick(coordinator)

        await Daemon(bridge, session_factory=runtime.session, on_tick=tick).run()
    except asyncio.CancelledError:
        pass
    except (OSError, ValueError, RuntimeError) as error:
        if runtime is not None:
            runtime.error = str(error)
        raise
    finally:
        try:
            if runtime is not None:
                runtime.stopped()
        finally:
            bridge.close()


def main():
    if sys.argv[1:2] == ["provision"]:
        from .provision import main as provision

        del sys.argv[1]
        return provision()
    parser = argparse.ArgumentParser(description="OpenASRInput exclusive cursor dictation")
    parser.add_argument("--version", action="version", version="OpenASRInput " + __version__)
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("demo", help="offline in-memory preedit/waveform demonstration")
    settings = subcommands.add_parser("settings", help="open this application's settings interface")
    settings.add_argument(
        "--config",
        help="explicit configuration file (default: XDG_CONFIG_HOME/openasrinput/input.json)",
    )
    settings.add_argument(
        "--port", type=int, default=int(os.environ.get("OPENASRINPUT_SETTINGS_PORT", "10088"))
    )
    settings.add_argument(
        "--no-open",
        action="store_true",
        help="print the local settings URL without opening a browser",
    )
    settings.add_argument(
        "--ready-file", help="private readiness record for the user-level settings launcher"
    )
    daemon = subcommands.add_parser("daemon", help="run the platform's native input bridge")
    daemon.add_argument("--config", help="the same configuration file used by settings")
    daemon.add_argument("--socket")
    daemon.add_argument("--portal-url")
    daemon.add_argument("--profile")
    daemon.add_argument("--device")
    check = subcommands.add_parser(
        "check-config",
        help="validate an explicit connection without audio, native bridge or network",
    )
    check.add_argument("--config")
    check.add_argument("--portal-url")
    check.add_argument("--profile")
    args = parser.parse_args()
    if args.command in (None, "demo"):
        demo()
        return
    from ..infrastructure.config import ConfigStore

    store = ConfigStore(args.config)
    if args.command == "settings":
        import asyncio

        if not 0 <= args.port <= 65535:
            parser.error("settings port must be between 0 and 65535")
        from ..presentation.settings_server import serve

        try:
            asyncio.run(
                serve(
                    store, port=args.port, open_window=not args.no_open, ready_file=args.ready_file
                )
            )
        except KeyboardInterrupt:
            pass
        except OSError as error:
            parser.exit(1, f"设置页无法监听 127.0.0.1:{args.port}：{error}\n")
        return

    from ..application.connection_config import effective_config, require_connection

    overrides = {}
    for name, key, value in (
        ("portal", "url", args.portal_url),
        ("portal", "profileId", args.profile),
        ("portal", "apiKey", os.environ.get("OPENASRINPUT_PORTAL_KEY")),
        ("audio", "deviceId", getattr(args, "device", None)),
        ("runtime", "socketPath", getattr(args, "socket", None)),
    ):
        if value is not None:
            overrides.setdefault(name, {})[key] = value
    try:
        config = effective_config(store.read()[0], overrides)
        if args.command == "check-config":
            require_connection(config)
    except (OSError, ValueError) as error:
        parser.exit(1, f"OpenASRInput: {error}\n")
    if args.command == "check-config":
        print(
            json.dumps(
                {
                    "configured": True,
                    "portalUrl": config["portal"]["url"],
                    "profileId": config["portal"]["profileId"],
                },
                ensure_ascii=False,
            )
        )
        return

    import asyncio

    try:
        asyncio.run(run_daemon(store, config["runtime"]["socketPath"], overrides))
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"OpenASRInput: {error}\n")


if __name__ == "__main__":
    main()
