import os
import sys
import json
import pytest

# Ensure repository and IWA module are importable in test envs
try:
    repo_root = os.path.abspath(os.getcwd())
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    iwa_root = os.path.join(repo_root, "autoppia_iwa_module")
    if os.path.isdir(iwa_root) and iwa_root not in sys.path:
        sys.path.insert(0, iwa_root)
except Exception:
    pass


def _have_network():
    # Simple heuristic: allow running; failures will skip gracefully
    return True


@pytest.mark.skipif(not _have_network(), reason="Network not available for IPFS test")
def test_ipfs_dataset_round_trip():
    try:
        # Try regular import; fallback to file-based import for CI environments
        try:
            from autoppia_web_agents_subnet.utils.ipfs_client import ipfs_add_json, ipfs_get_json
        except Exception:
            import importlib.util, pathlib
            ipfs_path = pathlib.Path(repo_root) / "autoppia_web_agents_subnet" / "utils" / "ipfs_client.py"
            spec = importlib.util.spec_from_file_location("ipfs_client", str(ipfs_path))
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            ipfs_add_json = mod.ipfs_add_json
            ipfs_get_json = mod.ipfs_get_json
        from autoppia_iwa.src.data_generation.domain.classes import Task
        from autoppia_iwa.src.execution.actions.base import BaseAction
        from autoppia_iwa.src.web_agents.classes import TaskSolution
    except Exception as e:
        pytest.skip(f"Required modules not available: {e}")

    # Build minimal task and dataset structures similar to validator dataset
    t = Task(url="https://example.com", prompt="Visit homepage", tests=[])
    task_entry = t.nested_model_dump()
    task_entry["id"] = t.id
    task_entry["web_project_id"] = "demo_project"

    solutions = [
        {
            "task_id": t.id,
            "miner_uid": 7,
            "actions": [
                {"type": "NavigateAction", "url": t.url},
            ],
        }
    ]
    evals = [
        {"task_id": t.id, "miner_uid": 7, "eval_score": 1.0, "time": 0.01}
    ]

    dataset = {
        "v": 1,
        "round": {"r": 1, "epoch_start": 0.0, "epoch_end": 1.0},
        "validator": {"uid": 123, "hotkey": "hk_demo", "version": "test", "validator_round_id": "vrid_demo"},
        "tasks": [task_entry],
        "solutions": solutions,
        "evals": evals,
    }

    # IPFS endpoint
    IPFS_API_URL = os.getenv("IPFS_API_URL", "http://ipfs.metahash73.com:5001/api/v0")

    # Upload to IPFS and fetch back
    try:
        cid, sha_hex, byte_len = ipfs_add_json(dataset, filename="test_dataset.json", api_url=IPFS_API_URL, pin=True, sort_keys=True)
    except Exception as e:
        pytest.skip(f"IPFS add failed: {e}")

    assert isinstance(cid, str) and len(cid) > 10
    assert isinstance(sha_hex, str) and len(sha_hex) == 64
    assert byte_len > 0

    try:
        obj, norm, h = ipfs_get_json(cid, api_url=IPFS_API_URL, expected_sha256_hex=sha_hex)
    except Exception as e:
        pytest.skip(f"IPFS get failed: {e}")

    # Structure checks
    assert isinstance(obj, dict)
    assert "tasks" in obj and isinstance(obj["tasks"], list)
    assert "solutions" in obj and isinstance(obj["solutions"], list)
    assert "evals" in obj and isinstance(obj["evals"], list)

    # Reconstruct Task and Actions to verify serializers are compatible
    try:
        t2 = Task.deserialize(obj["tasks"][0])
        assert t2.url == t.url
        assert t2.prompt == t.prompt
    except Exception as e:
        pytest.fail(f"Task.deserialize failed: {e}")

    try:
        acts = []
        for a in obj["solutions"][0].get("actions", []):
            act = BaseAction.create_action(a)
            assert act is not None
            acts.append(act)
        sol = TaskSolution(task_id=t2.id, actions=acts, web_agent_id=str(obj["solutions"][0]["miner_uid"]))
        assert len(sol.actions) == 1
    except Exception as e:
        pytest.fail(f"Action reconstruction failed: {e}")
