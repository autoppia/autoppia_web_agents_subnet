import sys
import time

import bittensor as bt

from autoppia_web_agents_subnet.base.miner import BaseMinerNeuron
from autoppia_web_agents_subnet.bittensor_config import config
from autoppia_web_agents_subnet.opensource.utils_git import normalize_and_validate_github_url
from autoppia_web_agents_subnet.protocol import StartRoundSynapse
from autoppia_web_agents_subnet.utils.env import _env_str
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

AGENT_NAME = _env_str("AGENT_NAME")
GITHUB_URL = _env_str("GITHUB_URL")
AGENT_IMAGE = _env_str("AGENT_IMAGE")


def _handshake_required_fields_status(agent_name: str, github_url: str) -> tuple[bool, list[str]]:
    """
    Validate required handshake fields and return readiness + human-readable reasons.
    Required fields: AGENT_NAME and GITHUB_URL (with explicit ref/commit).
    """
    reasons: list[str] = []

    if not agent_name:
        reasons.append("AGENT_NAME is empty or missing")

    if not github_url:
        reasons.append("GITHUB_URL is empty or missing")
    else:
        normalized, ref = normalize_and_validate_github_url(github_url, require_ref=True)
        if normalized is None:
            reasons.append("GITHUB_URL is invalid; expected https://github.com/<owner>/<repo>/tree/<ref> or /commit/<sha>")
        elif not ref:
            reasons.append("GITHUB_URL has no explicit ref/commit")

    return len(reasons) == 0, reasons


def _validate_miner_env() -> None:
    """Validate AGENT_NAME and GITHUB_URL at startup, exit on failure."""
    errors: list[str] = []

    if not (AGENT_NAME.strip() if isinstance(AGENT_NAME, str) else ""):
        errors.append("AGENT_NAME is not set. Validator will score this miner 0.")

    raw_url = GITHUB_URL.strip() if isinstance(GITHUB_URL, str) else ""
    if not raw_url:
        errors.append("GITHUB_URL is not set. Validator will score this miner 0.")
    elif normalize_and_validate_github_url(raw_url, require_ref=True)[0] is None:
        errors.append(f"GITHUB_URL is invalid: '{raw_url}'. Must be https://github.com/owner/repo/tree/<ref> or /commit/<sha>.")

    if errors:
        for err in errors:
            ColoredLogger.error(f"STARTUP VALIDATION FAILED: {err}", ColoredLogger.RED)
        sys.exit(1)


class Miner(BaseMinerNeuron):
    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)
        _validate_miner_env()

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

            required_ready, required_reasons = _handshake_required_fields_status(
                agent_name=agent_name,
                github_url=github_url,
            )
            if required_ready:
                ColoredLogger.success(
                    f"[StartRound] ✅ All required fields are ready to be evaluated: name='{agent_name}', github_url='{github_url}'",
                    ColoredLogger.GREEN,
                )
            else:
                if not agent_name and not github_url:
                    failure_scope = "name + github_url"
                elif not agent_name:
                    failure_scope = "name"
                elif not github_url:
                    failure_scope = "github_url"
                else:
                    # Covers format/ref issues in github_url.
                    failure_scope = "github_url"
                ColoredLogger.warning(
                    f"[StartRound] ❌ Required fields are NOT ready to be evaluated. failed={failure_scope} | reason={'; '.join(required_reasons)}",
                    ColoredLogger.YELLOW,
                )

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

            ColoredLogger.success(
                f"[StartRound] ✅ All fields set successfully! agent={agent_name or 'Unknown'}",
                ColoredLogger.GREEN,
            )

            # 🔍 DEBUG: Validate synapse before returning
            try:
                ColoredLogger.info("  Final synapse state:", ColoredLogger.GRAY)
                ColoredLogger.info(f"    - agent_name: {synapse.agent_name}", ColoredLogger.GRAY)
                ColoredLogger.info(f"    - github_url: {synapse.github_url}", ColoredLogger.GRAY)
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
