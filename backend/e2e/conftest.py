"""Boot the real stack for end-to-end tests.

Two real uvicorn processes on free ports:
  * the fake WooCommerce store (e2e/fake_store.py)
  * the ShopMind API in live WooCommerce mode, pointed at that store,
    with a throwaway SQLite file and the offline FakeLLM.

Tests then talk to ShopMind over HTTP only, exactly like the frontend does.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
WEBHOOK_SECRET = "e2e-webhook-secret"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url: str, proc: subprocess.Popen, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early:\n{proc.stdout.read().decode(errors='replace')}")
        try:
            if httpx.get(url, timeout=1, trust_env=False).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"{url} did not come up")


def _start(app: str, port: int, env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("SHOPMIND_")}
    base_env.update({"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})

    store_port, api_port = _free_port(), _free_port()
    store_url = f"http://127.0.0.1:{store_port}"
    api_url = f"http://127.0.0.1:{api_port}"
    db_file = tmp_path_factory.mktemp("e2e") / "shopmind.db"

    store = _start("e2e.fake_store:app", store_port, base_env)
    api_env = {
        **base_env,
        "SHOPMIND_DATABASE_URL": f"sqlite:///{db_file}",
        "SHOPMIND_LLM_PROVIDER": "fake",
        "SHOPMIND_WOO_MODE": "live",
        "SHOPMIND_WOO_STORE_URL": store_url,
        "SHOPMIND_WOO_CONSUMER_KEY": "ck_e2e",
        "SHOPMIND_WOO_CONSUMER_SECRET": "cs_e2e",
        "SHOPMIND_WOO_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "SHOPMIND_WOO_WRITEBACK": "true",
        "SHOPMIND_DEBUG": "false",
    }
    # Run from a temp cwd so backend/.env on a dev laptop can't leak in.
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
        cwd=db_file.parent, env={**api_env, "PYTHONPATH": str(BACKEND)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        _wait(f"{store_url}/_test/writes", store)
        _wait(f"{api_url}/health", api)
        with httpx.Client(base_url=api_url, timeout=30, trust_env=False) as client, \
                httpx.Client(base_url=store_url, timeout=10, trust_env=False) as store_client:
            yield {"api": client, "store": store_client}
    finally:
        for p in (api, store):
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


@pytest.fixture(scope="session")
def api(stack):
    return stack["api"]


@pytest.fixture(scope="session")
def store(stack):
    return stack["store"]
