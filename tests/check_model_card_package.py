"""Exercise the actual deb runtime locally; real cloud checks are explicit opt-in."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--electron", type=Path, required=True)
    parser.add_argument("--deepseek-config", type=Path)
    args = parser.parse_args()
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="model-card-package-", dir=results) as directory:
        folder = Path(directory)
        payload = folder / "package"
        subprocess.run(["dpkg-deb", "-x", str(args.package.resolve()), str(payload)], check=True)
        env = {**os.environ, "OPENASRINPUT_TEST_PACKAGE_ROOT": str(payload)}
        for test in ("test_settings_ui.cjs", "test_portal_cards_ui.cjs"):
            subprocess.run(
                [
                    "xvfb-run",
                    "-a",
                    str(args.electron.resolve()),
                    str(ROOT / "tests" / test),
                ],
                env=env,
                check=True,
                timeout=180,
            )
        if not args.deepseek_config:
            return
        original = args.deepseek_config.read_bytes()
        original_hash = hashlib.sha256(original).digest()
        editor = json.loads(original).get("textEdit", {})
        key = editor.get("apiKey")
        if not key:
            key = next(
                (
                    card.get("apiKey")
                    for card in editor.get("cards", [])
                    if card.get("url", "").startswith("https://api.deepseek.com")
                    and card.get("apiKey")
                ),
                None,
            )
        if not key:
            raise RuntimeError("No saved DeepSeek Key available")
        ready = folder / "ready.json"
        config = folder / "input.json"
        env = {
            **os.environ,
            "OPENASRINPUT_APP_ROOT": str(payload / "usr/lib/openasrinput"),
            "PYTHONPATH": "",
        }
        with (results / "model-card-package.log").open("w") as log:
            process = subprocess.Popen(
                [
                    str(payload / "usr/bin/openasrinput"),
                    "settings-server",
                    "--no-open",
                    "--port",
                    "0",
                    "--config",
                    str(config),
                    "--ready-file",
                    str(ready),
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(100):
                    if ready.exists():
                        break
                    if process.poll() is not None:
                        raise RuntimeError("Packaged settings exited")
                    time.sleep(0.1)
                origin, token = json.loads(ready.read_text())["url"].split("/#token=")

                def api(path, body=None, method=None):
                    request = Request(
                        origin + "/api/" + path,
                        data=json.dumps(body).encode() if body is not None else None,
                        method=method,
                        headers={
                            "Authorization": "Bearer " + token,
                            "Content-Type": "application/json",
                        },
                    )
                    with urlopen(request, timeout=75) as response:
                        return json.load(response)

                revision = api("config")["revision"]
                saved = []
                for provider in ("deepseek", "openai-compatible"):
                    card = {
                        "id": provider,
                        "name": provider + " 包内实测",
                        "provider": provider,
                        "url": "https://api.deepseek.com/v1",
                        "model": "",
                        "apiKey": key,
                    }
                    try:
                        api(
                            "config",
                            {"revision": revision, "patch": {"textEdit": {"cards": [card]}}},
                            "PATCH",
                        )
                    except HTTPError as error:
                        assert error.code == 400
                    else:
                        raise AssertionError("Incomplete card was accepted")
                    models = api("text-model/models", {"revision": revision, "card": card})[
                        "models"
                    ]
                    card["model"] = "deepseek-flash" if "deepseek-flash" in models else models[0]
                    assert api("text-model/test", {"revision": revision, "card": card})["ok"]
                    saved.append(card)
                    response = api(
                        "config",
                        {
                            "revision": revision,
                            "patch": {"textEdit": {"cards": saved, "activeModelCardId": provider}},
                        },
                        "PATCH",
                    )
                    revision = response["revision"]
                    assert key not in json.dumps(response)
                    assert response["config"]["textEdit"]["activeModelCardId"] == provider
                    print(
                        "PASS packaged", provider, "model discovery, completion, save and selection"
                    )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                assert hashlib.sha256(args.deepseek_config.read_bytes()).digest() == original_hash
        print("PASS local deb runtime; live configuration unchanged")


if __name__ == "__main__":
    main()
