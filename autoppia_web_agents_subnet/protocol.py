# file: autoppia_web_agents_subnet/protocol.py
"""
Shared protocol definitions between validator and miners.
These are the communication protocols used in Bittensor.
"""

from __future__ import annotations

from typing import Optional

from bittensor import Synapse


class StartRoundSynapse(Synapse):
    """
    Round handshake:
      - Validator -> Miner: announce a new round (metadata).
      - Miner -> Validator: respond with agent metadata for this round.

    Validator-populated (request):
      - round_id: unique identifier for the round.
      - validator_id: optional human-readable or wallet ID.
      - note: free-form context.

    Miner-populated (response):
      - agent_name: display name of the agent.
      - agent_image: URL (or data URI) to agent logo/avatar.
      - github_url: repository with miner/agent code.
      - agent_version / capabilities: optional details.
    """
    # Request (validator -> miner)
    version: str = ""
    round_id: str
    validator_id: Optional[str] = None
    note: Optional[str] = None

    # Response (miner -> validator)
    agent_name: Optional[str] = None
    github_url: Optional[str] = None
    agent_image: Optional[str] = None
    agent_version: Optional[str] = None
    has_rl: bool = False

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    def deserialize(self) -> "StartRoundSynapse":
        return self
