import time

import bittensor as bt

from autoppia_web_agents_subnet.utils.env import (
    _env_str, 
    _env_bool,
    _env_int, 
)

AGENT_NAME = _env_str("AGENT_NAME")
GITHUB_URL = _env_str("GITHUB_URL")
AGENT_IMAGE = _env_str("AGENT_IMAGE")
AGENT_VERSION = _env_int("AGENT_VERSION", 1)

from autoppia_web_agents_subnet.base.miner import BaseMinerNeuron
from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.bittensor_config import config


class Miner(BaseMinerNeuron):
    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)

    # ────────────────────────── Round Handshake ──────────────────────────
    async def forward(self, synapse: StartRoundSynapse) -> StartRoundSynapse:
        """
        Respond to a StartRound handshake with miner/agent metadata.
        No side-effects beyond logging and returning metadata.
        """
        try:
            validator_hotkey = getattr(synapse.dendrite, "hotkey", None)

            # 🔍 DEBUG: Log received synapse details
            ColoredLogger.info("=" * 80, ColoredLogger.CYAN)
            ColoredLogger.info(
                f"[StartRound] from validator: {validator_hotkey} round_id={getattr(synapse, 'round_id', '')}",
                ColoredLogger.YELLOW,
            )
            ColoredLogger.info(f"  - version: {getattr(synapse, 'version', 'NOT_SET')}", ColoredLogger.GRAY)
            ColoredLogger.info(f"  - validator_id: {getattr(synapse, 'validator_id', 'NOT_SET')}", ColoredLogger.GRAY)
            ColoredLogger.info("=" * 80, ColoredLogger.CYAN)

            # Respond with our metadata
            agent_name = AGENT_NAME.strip() if isinstance(AGENT_NAME, str) else ""
            agent_image = AGENT_IMAGE.strip() if isinstance(AGENT_IMAGE, str) else ""
            github_url = GITHUB_URL.strip() if isinstance(GITHUB_URL, str) else ""

            # 🔍 DEBUG: Set each field individually with error handling
            try:
                ColoredLogger.info(f"  Setting agent_name = {agent_name or None}", ColoredLogger.GRAY)
                synapse.agent_name = agent_name or None
            except Exception as e:
                ColoredLogger.error(f"  ❌ Failed to set agent_name: {e}", ColoredLogger.RED)
                raise

            try:
                ColoredLogger.info(f"  Setting agent_image = {agent_image[:50] if agent_image else None}...", ColoredLogger.GRAY)
                synapse.agent_image = agent_image or None
            except Exception as e:
                ColoredLogger.error(f"  ❌ Failed to set agent_image: {e}", ColoredLogger.RED)
                raise

            try:
                ColoredLogger.info(f"  Setting github_url = {github_url or None}", ColoredLogger.GRAY)
                synapse.github_url = github_url or None
            except Exception as e:
                ColoredLogger.error(f"  ❌ Failed to set github_url: {e}", ColoredLogger.RED)
                raise

            try:
                ColoredLogger.info(f"  Setting agent_version = {AGENT_VERSION}", ColoredLogger.GRAY)
                synapse.agent_version = AGENT_VERSION
            except Exception as e:
                ColoredLogger.error(f"  ❌ Failed to set agent_version: {e}", ColoredLogger.RED)
                raise

            ColoredLogger.success(
                f"[StartRound] ✅ All fields set successfully! agent={agent_name or 'Unknown'} v{AGENT_VERSION}",
                ColoredLogger.GREEN,
            )

            # 🔍 DEBUG: Validate synapse before returning
            try:
                ColoredLogger.info("  Final synapse state:", ColoredLogger.GRAY)
                ColoredLogger.info(f"    - agent_name: {synapse.agent_name}", ColoredLogger.GRAY)
                ColoredLogger.info(f"    - github_url: {synapse.github_url}", ColoredLogger.GRAY)
                ColoredLogger.info(f"    - agent_version: {synapse.agent_version}", ColoredLogger.GRAY)
            except Exception as e:
                ColoredLogger.warning(f"  ⚠️  Could not read synapse fields: {e}", ColoredLogger.YELLOW)

            return synapse
        except Exception as e:
            ColoredLogger.error(f"[StartRound] ERROR processing synapse: {e}", ColoredLogger.RED)
            bt.logging.error(f"[StartRound] Full error: {e}", exc_info=True)
            raise


if __name__ == "__main__":
    # Build config first to read CLI flags
    cfg = config(role="miner")

    with Miner(config=cfg) as miner:
        while True:
            time.sleep(5)
