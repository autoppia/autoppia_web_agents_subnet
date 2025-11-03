from __future__ import annotations

import asyncio
import copy
import hashlib
import itertools
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple, Type

import bittensor as bt  # type: ignore
import numpy as np


class MockKey:
    """Lightweight stand-in for bittensor key objects."""

    def __init__(self, *, ss58_address: str):
        self.ss58_address = ss58_address

    def sign(self, message: bytes) -> bytes:
        hasher = hashlib.sha256()
        hasher.update(self.ss58_address.encode("utf-8"))
        hasher.update(message)
        return hasher.digest()


class MockWallet:
    """Wallet shim exposing hotkey + coldkeypub attributes."""

    def __init__(
        self,
        *,
        name: str = "mock-wallet",
        hotkey_ss58: str = "5MockHotkey1111111111111111111111111",
        coldkey_ss58: Optional[str] = None,
    ):
        self.name = name
        self.hotkey = MockKey(ss58_address=hotkey_ss58)
        self.coldkeypub = MockKey(ss58_address=coldkey_ss58 or f"{hotkey_ss58}-cold")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<MockWallet hotkey={self.hotkey.ss58_address}>"


@dataclass
class MockAxonEndpoint:
    hotkey: str
    ip: str = "127.0.0.1"
    port: int = 8091
    version: int = 1
    proto: int = 0


class MockMetagraph:
    def __init__(self, hotkeys: Iterable[str]):
        keys = list(hotkeys)
        if not keys:
            raise ValueError("MockMetagraph requires at least one hotkey")

        self.hotkeys: List[str] = keys
        self.coldkeys: List[str] = [f"{hk}-cold" for hk in keys]
        self.axons: List[MockAxonEndpoint] = [MockAxonEndpoint(hotkey=hk) for hk in keys]
        self.uids = np.arange(len(keys), dtype=np.int64)
        self.n: int = len(keys)
        self.S: List[float] = [1.0 for _ in keys]
        self.stake: List[float] = list(self.S)
        self.validator_permit: List[bool] = [True for _ in keys]
        self.last_update: List[int] = [0 for _ in keys]

    def sync(self, subtensor: "MockSubtensor") -> None:
        block = subtensor.get_current_block()
        for idx in range(self.n):
            self.last_update[idx] = block


class MockSubtensor:
    def __init__(self, *, metagraph: MockMetagraph, network: str = "mock"):
        self._metagraph = metagraph
        self.network = network
        self.chain_endpoint = f"mock://{network}"
        self._block_counter = itertools.count(start=1, step=1)
        self._registrations: Dict[str, int] = {
            hk: idx for idx, hk in enumerate(self._metagraph.hotkeys)
        }
        self._commit_store: Dict[str, str] = {}
        self._last_set_weights: Dict[str, Dict[str, Any]] = {}

    def metagraph(self, netuid: int) -> MockMetagraph:  # noqa: ARG002
        return self._metagraph

    def is_hotkey_registered(self, *, netuid: int, hotkey_ss58: str) -> bool:  # noqa: ARG002
        return hotkey_ss58 in self._registrations

    def register_hotkey(self, hotkey_ss58: str, uid: Optional[int] = None) -> None:
        if uid is None:
            uid = len(self._registrations)
        self._registrations[hotkey_ss58] = uid

    def get_current_block(self) -> int:
        return next(self._block_counter)

    def serve_axon(self, *, netuid: int, axon: "MockAxon") -> bool:  # noqa: ARG002
        return True

    def min_allowed_weights(self, *, netuid: int) -> int:  # noqa: ARG002
        """Mirror bittensor min_allowed_weights behaviour."""
        return max(1, min(self._metagraph.n, 3))

    def max_weight_limit(self, *, netuid: int) -> float:  # noqa: ARG002
        """Return deterministic max weight limit for tests."""
        return 1.0

    def set_weights(  # pragma: no cover - exercised indirectly
        self,
        *,
        wallet: MockWallet,
        netuid: int,  # noqa: ARG002
        uids: List[int],
        weights: List[int],
        wait_for_finalization: bool = False,  # noqa: ARG002
        wait_for_inclusion: bool = False,  # noqa: ARG002
        version_key: Optional[int] = None,  # noqa: ARG002
    ) -> Tuple[bool, str]:
        """Store last weights broadcast by a wallet for inspection."""
        self._last_set_weights[wallet.hotkey.ss58_address] = {
            "uids": list(uids),
            "weights": list(weights),
            "version_key": version_key,
        }
        return True, "mock-ok"

    @property
    def commit_store(self) -> Dict[str, str]:
        return self._commit_store


class MockAsyncSubtensor:
    def __init__(self, *, subtensor: MockSubtensor):
        self._subtensor = subtensor

    async def commit(self, *, wallet: MockWallet, netuid: int, data: str, period: Optional[int] = None):  # noqa: ARG002
        self._subtensor.commit_store[wallet.hotkey.ss58_address] = data
        return True

    async def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int):  # noqa: ARG002
        try:
            return self._subtensor.metagraph(netuid).hotkeys.index(hotkey_ss58)
        except ValueError:
            return None

    async def get_commitment(self, *, netuid: int, uid: int, block: Optional[int] = None):  # noqa: ARG002
        metagraph = self._subtensor.metagraph(netuid)
        if uid < 0 or uid >= metagraph.n:
            return ""
        hotkey = metagraph.hotkeys[uid]
        return self._subtensor.commit_store.get(hotkey, "")

    async def get_all_commitments(self, *, netuid: int, block: Optional[int] = None, reuse_block: bool = False):  # noqa: ARG002
        return dict(self._subtensor.commit_store)


class MockNetworkRegistry:
    def __init__(self):
        self._handlers: Dict[str, Callable[[Any], Awaitable[Any] | Any]] = {}

    def register(self, hotkey: str, handler: Callable[[Any], Awaitable[Any] | Any]) -> None:
        self._handlers[hotkey] = handler

    def unregister(self, hotkey: str) -> None:
        self._handlers.pop(hotkey, None)

    async def dispatch(self, hotkey: str, synapse: Any) -> Any:
        handler = self._handlers.get(hotkey)
        if handler is None:
            return None
        result = handler(synapse)
        if asyncio.iscoroutine(result):
            return await result
        return result


_GLOBAL_NETWORK = MockNetworkRegistry()


def get_mock_network() -> MockNetworkRegistry:
    return _GLOBAL_NETWORK


def reset_mock_network() -> None:
    _GLOBAL_NETWORK._handlers.clear()


class MockAxon:
    def __init__(self, *, wallet: MockWallet):
        self.wallet = wallet
        self.external_ip = "127.0.0.1"
        self.external_port = 8091
        self._handlers: Dict[Type[Any], Tuple[Callable, Callable]] = {}
        self._network = get_mock_network()

    def attach(self, *, forward_fn: Callable, blacklist_fn: Callable, priority_fn: Callable):  # noqa: ARG002
        from autoppia_web_agents_subnet.protocol import (  # lazy import to avoid circular
            StartRoundSynapse,
            TaskFeedbackSynapse,
            TaskSynapse,
        )

        mapping = {
            "forward": TaskSynapse,
            "forward_feedback": TaskFeedbackSynapse,
            "forward_start_round": StartRoundSynapse,
        }

        key = mapping.get(forward_fn.__name__)
        if key is None:
            raise ValueError(f"Unsupported forward function name '{forward_fn.__name__}' for MockAxon")

        self._handlers[key] = (forward_fn, blacklist_fn)

    def serve(self, *, netuid: int, subtensor: MockSubtensor) -> None:  # noqa: ARG002
        self._network.register(self.wallet.hotkey.ss58_address, self._dispatch)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self._network.unregister(self.wallet.hotkey.ss58_address)

    async def _dispatch(self, synapse: Any):
        for syn_cls, (forward_fn, blacklist_fn) in self._handlers.items():
            if isinstance(synapse, syn_cls):
                blocked, _ = await blacklist_fn(synapse)
                if blocked:
                    return None
                result = forward_fn(synapse)
                if asyncio.iscoroutine(result):
                    result = await result
                if result is not None:
                    try:
                        object.__setattr__(result, 'dendrite', SimpleNamespace(status_code=200, hotkey=self.wallet.hotkey.ss58_address))
                    except Exception:
                        try:
                            result.__dict__['dendrite'] = SimpleNamespace(status_code=200, hotkey=self.wallet.hotkey.ss58_address)
                        except Exception:
                            pass
                return result
        raise RuntimeError(f"No handler registered for synapse type: {type(synapse)}")


class MockDendrite:
    def __init__(self, *, wallet: MockWallet):
        self.wallet = wallet
        self._network = get_mock_network()

    async def __call__(
        self,
        *,
        axons: List[MockAxonEndpoint],
        synapse: Any,
        deserialize: bool = True,  # noqa: ARG002
        timeout: Optional[int] = None,  # noqa: ARG002
        retries: int = 0,  # noqa: ARG002
        retry: Optional[bool] = None,  # noqa: ARG002
    ) -> List[Any]:
        responses: List[Any] = []
        for axon in axons:
            payload = copy.deepcopy(synapse)
            try:
                object.__setattr__(payload, 'dendrite', SimpleNamespace(hotkey=self.wallet.hotkey.ss58_address, status_code=200))
            except Exception:
                try:
                    payload.__dict__['dendrite'] = SimpleNamespace(hotkey=self.wallet.hotkey.ss58_address, status_code=200)
                except Exception:
                    pass
            resp = await self._network.dispatch(axon.hotkey, payload)
            responses.append(resp)
        return responses


@dataclass
class MockNeuronContext:
    wallet: MockWallet
    subtensor: MockSubtensor
    metagraph: MockMetagraph
    async_subtensor: MockAsyncSubtensor | None = field(init=False, default=None)

    def __post_init__(self):
        self.async_subtensor = MockAsyncSubtensor(subtensor=self.subtensor)
