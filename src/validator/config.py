import argparse
import bittensor as bt


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

    parser.add_argument(
        "--generation.endpoints",
        "--generation.endpoint",
        type=str,
        nargs="*",
        help="Specifies the URL of the endpoint responsible for generating 3D assets. "
             "This endpoint should handle the /generation/ POST route.",
        default=["http://127.0.0.1:8093"],
    )

    parser.add_argument(
        "--llm.endpoint",
        type=str,
        help="URL for the LLM endpoint",
        default="http://localhost:6000/generate",
    )

    parser.add_argument(
        "--demo_webs.endpoint",
        type=str,
        help="URL for the demo webs endpoint",
        default="http://localhost",
    )

    parser.add_argument(
        "--demo_webs_starting_port",
        type=int,
        help="Starting port for the demo webs service",
        default=6000,
    )

    return bt.config(parser)
