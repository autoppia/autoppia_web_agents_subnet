import argparse
import bittensor as bt

TIMEOUT = 60 * 2  # 2 Min
CHECK_VERSIONS_SYNAPSE = 30
FEEDBACK_TIMEOUT = 30
FORWARD_SLEEP_SECONDS = 60 * 1  # 1 Minutes
TASK_SLEEP = 60 * 1  # 1 Minute
TIME_WEIGHT = 0.2
MIN_SCORE_FOR_CORRECT_FORMAT = 0.1  # 10%
MIN_RESPONSE_REWARD = 0
SAMPLE_SIZE = 256  # Number of Miners
MAX_ACTIONS_LENGTH = 15
NUM_URLS = 1
PROMPTS_PER_ITERATION = 1
CHECK_VERSION_PROBABILITY = 0.25


def read_config() -> bt.config:
    parser = argparse.ArgumentParser()
    bt.logging.add_args(parser)
    bt.wallet.add_args(parser)
    bt.subtensor.add_args(parser)
    bt.axon.add_args(parser)

    parser.add_argument("--netuid", type=int, help="Subnet netuid", default=36)

    parser.add_argument(
        "--neuron.name",
        type=str,
        help="Name of the neuron, used to determine the neuron directory",
        default="validator",
    )

    parser.add_argument("--neuron.sync_interval", type=int, help="Metagraph sync interval, seconds", default=30 * 60)

    return bt.config(parser)
