import time
from typing import List

import bittensor as bt

from autoppia_web_agents_subnet.base.miner import BaseMinerNeuron
from autoppia_web_agents_subnet.protocol import (
    TaskSynapse,
    TaskFeedbackSynapse,
    StartRoundSynapse,
)
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.miner.models import MinerStats
from autoppia_web_agents_subnet.bittensor_config import config

# IWA dependencies (agent + task types)
from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.web_agents.random.agent import RandomClickerWebAgent
from autoppia_iwa.src.web_agents.apified_agent import ApifiedWebAgent
from autoppia_iwa.config.config import (
    AGENT_HOST,
    AGENT_PORT,
    USE_APIFIED_AGENT,
)

from autoppia_web_agents_subnet.miner.logging import print_task_feedback

# Miner configuration
from autoppia_web_agents_subnet.miner.config import (
    AGENT_NAME,
    AGENT_IMAGE,
    GITHUB_URL,
    AGENT_VERSION,
    HAS_RL,
)


class Miner(BaseMinerNeuron):
    def __init__(self, config=None):
        super(Miner, self).__init__(config=config)

        # Choose agent implementation
        self.agent = ApifiedWebAgent(name=AGENT_NAME, host=AGENT_HOST, port=AGENT_PORT) if USE_APIFIED_AGENT else RandomClickerWebAgent(is_random=False)

        self.miner_stats = MinerStats()
        self.load_state()

    # ────────────────────────── Round Handshake ──────────────────────────
    async def forward_start_round(self, synapse: StartRoundSynapse) -> StartRoundSynapse:
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
            ColoredLogger.info(f"  - total_prompts: {getattr(synapse, 'total_prompts', 'NOT_SET')}", ColoredLogger.GRAY)
            ColoredLogger.info(f"  - has_rl (received): {getattr(synapse, 'has_rl', 'NOT_SET')}", ColoredLogger.GRAY)
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

            try:
                ColoredLogger.info(f"  Setting has_rl = {HAS_RL} (type: {type(HAS_RL)})", ColoredLogger.GRAY)
                synapse.has_rl = HAS_RL
            except Exception as e:
                ColoredLogger.error(f"  ❌ Failed to set has_rl: {e}", ColoredLogger.RED)
                raise

            ColoredLogger.success(
                f"[StartRound] ✅ All fields set successfully! agent={agent_name or 'Unknown'} v{AGENT_VERSION} RL={HAS_RL}",
                ColoredLogger.GREEN,
            )

            # 🔍 DEBUG: Validate synapse before returning
            try:
                ColoredLogger.info("  Final synapse state:", ColoredLogger.GRAY)
                ColoredLogger.info(f"    - agent_name: {synapse.agent_name}", ColoredLogger.GRAY)
                ColoredLogger.info(f"    - agent_version: {synapse.agent_version}", ColoredLogger.GRAY)
                ColoredLogger.info(f"    - has_rl: {synapse.has_rl}", ColoredLogger.GRAY)
            except Exception as e:
                ColoredLogger.warning(f"  ⚠️  Could not read synapse fields: {e}", ColoredLogger.YELLOW)

            return synapse
        except Exception as e:
            ColoredLogger.error(f"[StartRound] ERROR processing synapse: {e}", ColoredLogger.RED)
            bt.logging.error(f"[StartRound] Full error: {e}", exc_info=True)
            raise

    # ───────────────────────────── Tasks ─────────────────────────────
    def _show_actions(self, actions: List[BaseAction]) -> None:
        """Pretty-prints the list of actions in a more readable format."""
        if not actions:
            bt.logging.warning("No actions to log.")
            return

        bt.logging.debug("Actions sent:")
        for i, action in enumerate(actions, 1):
            action_attrs = vars(action)
            ColoredLogger.debug(
                f"    {i}. {action.type}: {action_attrs}",
                ColoredLogger.GREEN,
            )
            bt.logging.debug(f"  {i}. {action.type}: {action_attrs}")

    async def forward(self, synapse: TaskSynapse) -> TaskSynapse:
        validator_hotkey = getattr(synapse.dendrite, "hotkey", None)
        ColoredLogger.info(
            f"Request Received from validator: {validator_hotkey}",
            ColoredLogger.YELLOW,
        )

        try:
            start_time = time.time()

            seed = getattr(synapse, "seed", None)
            url = synapse.url

            if seed is None and isinstance(url, str):
                try:
                    from urllib.parse import parse_qs, urlparse

                    parsed = urlparse(url)
                    query = parse_qs(parsed.query or "")
                    raw_seed = query.get("seed", [None])[0]
                    if raw_seed is not None:
                        seed = int(str(raw_seed))
                except (ValueError, TypeError):
                    seed = None

            if seed is not None and isinstance(url, str) and "seed=" not in url:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}seed={seed}"
                synapse.url = url

            synapse_seed = getattr(synapse, "seed", None)
            if seed is not None:
                if synapse_seed is None:
                    synapse.seed = int(seed)
                elif int(synapse_seed) != int(seed):
                    ColoredLogger.warning(
                        f"Seed mismatch detected: synapse.seed={synapse_seed} url_seed={seed}",
                        ColoredLogger.YELLOW,
                    )
                    synapse.seed = int(seed)

            task = Task(
                prompt=synapse.prompt,
                url=url,
            )

            if seed is not None:
                try:
                    task.assign_seed = False
                    object.__setattr__(task, "_seed_value", int(seed))
                except Exception as err:
                    ColoredLogger.warning(f"Unable to set task seed: {err}", ColoredLogger.YELLOW)
            else:
                ColoredLogger.debug("Received task without seed.", ColoredLogger.YELLOW)

            task_for_agent = task.prepare_for_agent(str(self.uid))

            ColoredLogger.debug(f"Task Prompt: {task_for_agent.prompt}", ColoredLogger.BLUE)
            bt.logging.info("Generating actions...")

            # Process the task
            task_solution = await self.agent.solve_task(task=task_for_agent)
            task_solution.web_agent_id = str(self.uid)
            actions: List[BaseAction] = task_solution.replace_web_agent_id()

            self._show_actions(actions)

            # Assign actions back to the synapse
            synapse.actions = actions

            ColoredLogger.success(
                f"Request completed successfully in {time.time() - start_time:.2f}s",
                ColoredLogger.GREEN,
            )
        except Exception as e:
            bt.logging.error(f"An error occurred on miner forward: {e}")

        return synapse

    # ─────────────────────────── Feedback ───────────────────────────
    async def forward_feedback(self, synapse: TaskFeedbackSynapse) -> TaskFeedbackSynapse:
        """
        Endpoint for feedback requests from the validator.
        Logs the feedback, updates MinerStats, and prints a summary.
        """
        ColoredLogger.info("Received feedback", ColoredLogger.GRAY)

        # DEBUG: Log detailed TaskFeedbackSynapse content
        ColoredLogger.info("🔍 DEBUG TaskFeedbackSynapse content:", ColoredLogger.YELLOW)
        ColoredLogger.info(f"  - task_id: {synapse.task_id}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - score: {synapse.score}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - execution_time: {synapse.execution_time}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - tests: {synapse.tests}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - test_results: {synapse.test_results}", ColoredLogger.GRAY)
        ColoredLogger.info(f"  - actions: {len(synapse.actions) if synapse.actions else 0} actions", ColoredLogger.GRAY)

        # Show evaluation_result but replace GIF content with just its length
        eval_result_display = None
        if synapse.evaluation_result:
            eval_result_display = synapse.evaluation_result.copy()
            if "gif_recording" in eval_result_display and eval_result_display["gif_recording"]:
                eval_result_display["gif_recording"] = f"<length: {len(eval_result_display['gif_recording'])}>"

        ColoredLogger.info(f"  - evaluation_result: {eval_result_display}", ColoredLogger.GRAY)

        # 🔍 DEBUG: Log web project details
        ColoredLogger.info("  📦 WEB PROJECT DETAILS:", ColoredLogger.MAGENTA)
        ColoredLogger.info(f"     - Web Project: {getattr(synapse, 'web_project_name', 'N/A')}", ColoredLogger.MAGENTA)
        ColoredLogger.info(f"     - Task URL: {synapse.task_url}", ColoredLogger.MAGENTA)

        try:
            # Defensive defaults
            score = float(synapse.score or 0.0)
            exec_time = float(synapse.execution_time or 0.0)

            self.miner_stats.log_feedback(score, exec_time)
            print_task_feedback(synapse, self.miner_stats)
        except Exception as e:
            ColoredLogger.error("Error occurred while printing TaskFeedback in terminal")
            raise e

        return synapse


if __name__ == "__main__":
    # Build config first to read CLI flags
    cfg = config(role="miner")
    # Initializing Dependency Injection In IWA with logging level
    try:
        iwa_debug = False
        if hasattr(cfg, "iwa") and hasattr(cfg.iwa, "logging") and hasattr(cfg.iwa.logging, "debug"):
            iwa_debug = bool(cfg.iwa.logging.debug)
        AppBootstrap(debug=iwa_debug)
    except Exception:
        pass

    with Miner(config=cfg) as miner:
        while True:
            time.sleep(5)
