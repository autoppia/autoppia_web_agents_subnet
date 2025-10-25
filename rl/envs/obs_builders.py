from __future__ import annotations

import hashlib
import re
from typing import Deque, Iterable, List

import numpy as np
from gymnasium import spaces

from .types import BrowserSnapshot, RankResult, TaskSpec


def _tokenize(text: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip().lower()
    return [token for token in re.split(r"[^\w]+", normalized) if token]


class ObservationBuilder:
    """Transforms browser and task state into PPO friendly tensors."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.goal_vocab = int(cfg.get("goal_vocab_size", 4096))
        self.dom_vocab = int(cfg.get("dom_vocab_size", 8192))
        self.url_vocab = int(cfg.get("url_vocab_size", 1024))
        self.max_goal_tokens = int(cfg.get("max_goal_tokens", 64))
        self.max_dom_tokens = int(cfg.get("max_dom_tokens", 256))
        self.max_element_tokens = int(cfg.get("max_element_tokens", 12))
        self.history_length = int(cfg.get("action_history", 10))
        self.topk_meta_dim = int(cfg.get("topk_meta_dim", 6))
        self.max_cart_items = float(cfg.get("max_cart_items", 10.0))

    # ------------------------------------------------------------------
    # Gym spaces
    # ------------------------------------------------------------------
    def space(self, action_space_n: int, top_k: int) -> spaces.Dict:
        return spaces.Dict(
            {
                "goal_ids": spaces.Box(
                    low=0,
                    high=self.goal_vocab,
                    shape=(self.max_goal_tokens,),
                    dtype=np.int32,
                ),
                "dom_ids": spaces.Box(
                    low=0,
                    high=self.dom_vocab,
                    shape=(self.max_dom_tokens,),
                    dtype=np.int32,
                ),
                "url_id": spaces.Box(low=0, high=self.url_vocab, shape=(1,), dtype=np.int32),
                "prev_actions": spaces.Box(
                    low=0,
                    high=action_space_n,
                    shape=(self.history_length,),
                    dtype=np.int32,
                ),
                "topk_meta": spaces.Box(
                    low=0.0,
                    high=1.0,
                    shape=(top_k, self.topk_meta_dim),
                    dtype=np.float32,
                ),
                "topk_text_ids": spaces.Box(
                    low=0,
                    high=self.dom_vocab,
                    shape=(top_k, self.max_element_tokens),
                    dtype=np.int32,
                ),
                "inputs_filled_ratio": spaces.Box(
                    low=0.0,
                    high=1.0,
                    shape=(1,),
                    dtype=np.float32,
                ),
                "cart_items": spaces.Box(
                    low=0.0,
                    high=self.max_cart_items,
                    shape=(1,),
                    dtype=np.float32,
                ),
            }
        )

    # ------------------------------------------------------------------
    # Encoding helpers
    # ------------------------------------------------------------------
    def _hash_token(self, token: str, vocab: int) -> int:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        return int.from_bytes(digest, "little") % vocab

    def _encode_tokens(self, tokens: Iterable[str], limit: int, vocab: int) -> np.ndarray:
        arr = np.zeros((limit,), dtype=np.int32)
        for idx, token in enumerate(tokens):
            if idx >= limit:
                break
            arr[idx] = self._hash_token(token, vocab)
        return arr

    def _encode_text(self, text: str, limit: int, vocab: int) -> np.ndarray:
        return self._encode_tokens(_tokenize(text), limit, vocab)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build(
        self,
        task: TaskSpec,
        snapshot: BrowserSnapshot,
        rank: RankResult,
        action_history: Deque[int],
        top_k: int,
    ) -> dict:
        obs = {
            "goal_ids": self._encode_text(task.goal, self.max_goal_tokens, self.goal_vocab),
            "dom_ids": self._encode_text(snapshot.dom_text, self.max_dom_tokens, self.dom_vocab),
            "url_id": np.array(
                [self._hash_token(snapshot.url or "", self.url_vocab)], dtype=np.int32
            ),
            "prev_actions": self._encode_history(action_history),
            "topk_meta": self._encode_meta(rank, top_k),
            "topk_text_ids": self._encode_topk_text(rank, top_k),
            "inputs_filled_ratio": np.array(
                [self._inputs_filled_ratio(snapshot)], dtype=np.float32
            ),
            "cart_items": np.array([float(snapshot.cart_items)], dtype=np.float32),
        }
        return obs

    def _encode_history(self, history: Deque[int]) -> np.ndarray:
        arr = np.zeros((self.history_length,), dtype=np.int32)
        for idx, action in enumerate(list(history)[-self.history_length :]):
            arr[idx] = int(action)
        return arr

    def _encode_meta(self, rank: RankResult, top_k: int) -> np.ndarray:
        arr = np.zeros((top_k, self.topk_meta_dim), dtype=np.float32)
        for row, ranked in enumerate(rank.padded_elements(top_k)[:top_k]):
            features = np.asarray(ranked.meta_features, dtype=np.float32)
            limit = min(len(features), self.topk_meta_dim)
            arr[row, :limit] = features[:limit]
        return arr

    def _encode_topk_text(self, rank: RankResult, top_k: int) -> np.ndarray:
        arr = np.zeros((top_k, self.max_element_tokens), dtype=np.int32)
        for row, ranked in enumerate(rank.padded_elements(top_k)[:top_k]):
            arr[row] = self._encode_text(ranked.element.text, self.max_element_tokens, self.dom_vocab)
        return arr

    def _inputs_filled_ratio(self, snapshot: BrowserSnapshot) -> float:
        values = snapshot.inputs_state.values
        if not values:
            return 0.0
        filled = sum(1 for value in values.values() if value)
        return min(1.0, filled / max(len(values), 1))


__all__ = ["ObservationBuilder"]
