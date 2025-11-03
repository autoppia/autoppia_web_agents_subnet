import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


REQUIRED_ENV_VARS = [
    "BT_TEST_WALLET_NAME",
    "BT_TEST_HOTKEY_NAME",
    "BT_TEST_NETUID",
    "BT_TEST_NETWORK",
]


def _has_required_env() -> bool:
    return all(os.getenv(var) for var in REQUIRED_ENV_VARS)


@pytest.mark.requires_finney
def test_validator_round_mainnet(tmp_path: Path):
    """
    Smoke-test that launches the validator inside a subprocess using the
    prepared test wallet/hotkey. This test is skipped unless the required
    environment variables are provided, because it interacts with a live
    Subtensor network.
    """
    if not _has_required_env():
        pytest.skip(
            "Set BT_TEST_WALLET_NAME, BT_TEST_HOTKEY_NAME, BT_TEST_NETUID, BT_TEST_NETWORK to enable on-chain test."
        )

    repo_root = Path(__file__).resolve().parents[2]
    validator_script = repo_root / "neurons" / "validator.py"
    assert validator_script.exists()

    env = os.environ.copy()
    # Speed up the round for CI by using testing overrides.
    env.setdefault("TESTING", "true")
    env.setdefault("TEST_PRE_GENERATED_TASKS", "2")
    env.setdefault("ENABLE_DISTRIBUTED_CONSENSUS", "false")
    env.setdefault("ENABLE_FINAL_LOCAL", "false")
    env.setdefault("ENABLE_CHECKPOINT_SYSTEM", "true")

    cmd = [
        sys.executable,
        str(validator_script),
        "--netuid",
        os.environ["BT_TEST_NETUID"],
        "--subtensor.network",
        os.environ["BT_TEST_NETWORK"],
        "--wallet.name",
        os.environ["BT_TEST_WALLET_NAME"],
        "--wallet.hotkey",
        os.environ["BT_TEST_HOTKEY_NAME"],
        "--logging.debug",
    ]

    process = subprocess.Popen(
        cmd,
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    deadline = time.time() + 180
    success_marker = "🧭 Phase → complete"
    stdout = []

    try:
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                time.sleep(0.5)
                continue
            stdout.append(line)
            if success_marker in line.lower():
                break
        else:
            raise TimeoutError("Validator did not complete round within timeout.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    if process.returncode not in (0, None):
        pytest.fail(f"Validator subprocess exited with {process.returncode}\n{''.join(stdout)}")
