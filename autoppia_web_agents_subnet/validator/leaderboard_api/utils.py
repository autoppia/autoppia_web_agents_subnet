import bittensor as bt
from autoppia_web_agents_subnet import __version__
from autoppia_web_agents_subnet.validator.leaderboard_api.leaderboard_runs import (
    upsert_validator_info,
)
from autoppia_iwa_module.autoppia_iwa.config.config import (
    LLM_PROVIDER,
    LLM_CONTEXT_WINDOW,
    LLM_THRESHOLD,
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
    LOCAL_MODEL_ENDPOINT,
    EVALUATOR_HEADLESS,
    GENERATE_MILESTONES,
    DEMO_WEBS_ENDPOINT,
    DEMO_WEBS_STARTING_PORT,
    OPERATOR_ENDPOINT,
)


def build_validator_info_doc(validator) -> dict:
    """
    Build the JSON payload for validator_info from wallet, metagraph and .env config.
    """
    try:
        validator_id = int(validator.uid)
    except Exception:
        validator_id = -1

    try:
        address = str(validator.wallet.hotkey.ss58_address)
    except Exception:
        address = ""
    try:
        hotkey = str(validator.wallet.hotkey_str)
    except Exception:
        hotkey = ""
    try:
        coldkey = str(validator.wallet.coldkeypub.ss58_address)
    except Exception:
        coldkey = ""

    return {
        "_id": f"validator:{validator_id}",
        "validator_id": validator_id,
        "address": address,
        "hotkey": hotkey,
        "coldkey": coldkey,
        "version": __version__,
        "llm": {
            "provider": LLM_PROVIDER,
            "context_window": int(LLM_CONTEXT_WINDOW),
            "threshold": int(LLM_THRESHOLD),
            "openai_model": OPENAI_MODEL,
            "openai_temperature": float(OPENAI_TEMPERATURE),
            "local_endpoint": LOCAL_MODEL_ENDPOINT,
        },
        "evaluator": {
            "headless": bool(EVALUATOR_HEADLESS),
            "generate_milestones": bool(GENERATE_MILESTONES),
        },
        "operator": {"endpoint": OPERATOR_ENDPOINT},
        "demo_webs": {
            "endpoint": DEMO_WEBS_ENDPOINT,
            "starting_port": int(DEMO_WEBS_STARTING_PORT),
        },
    }


def send_validator_run_info(validator) -> None:
    """
    Build and send validator_info to the Leaderboard API.
    """
    doc = build_validator_info_doc(validator)
    upsert_validator_info(doc)
    bt.logging.success("validator_info sent to Leaderboard API.")
