import socket
import tempfile
import threading
import unittest
from pathlib import Path

from openasrinput.adapters.native import NativeBridge
from openasrinput.infrastructure.config import ROOT


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix native bridge")
class NativeDiagnosticsTests(unittest.TestCase):
    def test_optional_diagnostic_probe_keeps_older_v1_peer_usable(self):
        with tempfile.TemporaryDirectory(prefix="nd-", dir=ROOT / "test-results") as directory:
            path = str(Path(directory) / "n.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(path)
            listener.listen()
            requests = []

            def serve():
                peer, _ = listener.accept()
                with peer, peer.makefile("rb") as lines:
                    peer.sendall(b"0\tHELLO\tOpenASRInput.Bridge\t1\n")
                    for line in lines:
                        identity, verb, *_ = line.decode().strip().split("\t")
                        requests.append(verb)
                        response = (
                            "ERROR\tinvalid-request" if verb == "CONTEXT_STATUS" else "OK\ttrue"
                        )
                        peer.sendall(f"{identity}\t{response}\n".encode())

            thread = threading.Thread(target=serve)
            thread.start()
            bridge = NativeBridge(path)
            try:
                self.assertEqual(bridge.context_status(), {})
                self.assertEqual(bridge.context_status(), {})
                self.assertEqual(bridge.request("VALID", "legacy"), "true")
            finally:
                bridge.close()
                thread.join(timeout=2)
                listener.close()
            self.assertEqual(requests, ["CONTEXT_STATUS", "VALID"])
