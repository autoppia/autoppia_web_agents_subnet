import pytest

from autoppia_web_agents_subnet.platform.utils import round_flow


class RoundManagerStub:
    BLOCKS_PER_EPOCH = 360

    def get_current_boundaries(self):
        return {
            "round_start_epoch": 10.0,
            "target_epoch": 11.0,
        }

    async def calculate_round(self, current_block):
        return current_block // self.BLOCKS_PER_EPOCH


class OfflineIWAPClient:
    async def auth_check(self):
        raise RuntimeError("offline")


@pytest.mark.asyncio
async def test_start_round_flow_enters_offline_mode(monkeypatch):
    rm = RoundManagerStub()
    ctx = type(
        "Ctx",
        (),
        {
            "current_round_id": "round-1",
            "round_manager": rm,
            "round_start_timestamp": 0.0,
            "uid": 0,
            "active_miner_uids": [],
            "current_round_tasks": {},
            "_phases": {"p1_done": False, "p2_done": False},
            "iwap_client": OfflineIWAPClient(),
            "round_handshake_payloads": {},
            "current_agent_runs": {},
            "current_miner_snapshots": {},
            "agent_run_accumulators": {},
            "version": "1.0.0",
            "wallet": type(
                "W",
                (),
                {
                    "hotkey": type("HK", (), {"ss58_address": "v-hotkey"})(),
                    "coldkeypub": type("CK", (), {"ss58_address": "v-cold"})(),
                },
            )(),
            "metagraph": type(
                "MG",
                (),
                {
                    "stake": [1.0],
                    "hotkeys": ["v-hotkey"],
                    "S": [1.0],
                    "validator_permit": [True],
                },
            )(),
            "_save_round_state": lambda self=None: None,
        },
    )()

    await round_flow.start_round_flow(ctx, current_block=360, n_tasks=1)

    assert ctx._phases["p1_done"] is True
    assert ctx._phases["p2_done"] is True
    assert getattr(ctx, "_iwap_offline_mode", False) is True
