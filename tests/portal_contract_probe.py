"""Explicit integration probe for a disposable Portal with a synthetic provider.

It sends synthetic PCM and only commits to an in-memory host. Do not point it at
an existing Portal: the integration instructions start a dedicated test instance.
"""

import argparse
import asyncio

from openasrinput.adapters.portal import PortalClient
from openasrinput.application.controller import Controller
from openasrinput.domain.bridge import MemoryBridge


async def probe(url):
    host = MemoryBridge()
    host.focus("probe")
    core = Controller(host)
    async with PortalClient(url, "client-key") as client:
        await client.capabilities()
        vocabulary = await client.hotwords()
        assert vocabulary["version"] == 1 and not vocabulary["settings"]["autoLearn"]
        assert not vocabulary["settings"]["enabled"]
        vocabulary = await client.hotwords(
            "PATCH",
            {
                "revision": vocabulary["revision"],
                "settings": {
                    "enabled": True,
                    "autoLearn": True,
                    "minFrequency": 2,
                    "manualTerms": [{"text": "麒麟", "weight": 4}],
                },
            },
        )
        assert vocabulary["terms"][0]["text"] == "麒麟"
        assert not vocabulary["selection"]["capability"]["supported"]  # local fixture
        session_ids = []
        for _ in range(2):
            core.toggle()
            core.take_effects()
            session = await client.create_session()
            session_ids.append(session["sessionId"])
            generation = core.generation
            assert core.bind_session(generation, session["sessionId"])
            async with client.stream(session) as stream:
                core.on_event(generation, stream.ready_event)
                core.take_effects()
                await stream.send_pcm(bytes(640))
                core.toggle()
                assert [e.kind for e in core.take_effects()] == ["audio.stop-flush", "audio.end"]
                await stream.end_audio()
                while not stream.ledger.terminal:
                    event = await stream.receive()
                    core.on_event(generation, event)
                    core.drain()
            assert core.state == "paused", core.error
            core.take_effects()
        assert session_ids[0] != session_ids[1]
        assert len(host.commits) == 2
        assert all(text == "最终文本。" for _, _, text in host.commits)
        # Cancelling a separate session must not affect a concurrent one.
        first, second = await client.create_session(), await client.create_session()
        async with client.stream(first) as one, client.stream(second) as two:
            await one.cancel()
            while not one.ledger.terminal:
                await one.receive()
            assert one.ledger.final_count == 0
            await two.end_audio()
            while not two.ledger.terminal:
                await two.receive()
            assert two.ledger.final_count == 1
        vocabulary = await client.hotwords()
        assert vocabulary["learnedTerms"]
        await client.clear_hotword_statistics()
        vocabulary = await client.hotwords()
        assert not vocabulary["learnedTerms"] and vocabulary["terms"][0]["text"] == "麒麟"
    print(
        "Portal v1 integration passed: default profile, pause/resume, PCM16, finals, cancellation isolation, personal hotwords"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    asyncio.run(probe(args.url))
