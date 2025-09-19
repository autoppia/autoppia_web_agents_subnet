import sys
import time
from pathlib import Path

import bittensor as bt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.validator.forward import forward

from autoppia_iwa.src.bootstrap import AppBootstrap
from loguru import logger


class Validator(BaseValidatorNeuron):

    def __init__(self, config=None):
        super(Validator, self).__init__(config=config)

        self.forward_count = 0

        bt.logging.info("load_state()")
        self.load_state()

    async def forward(self):

        return await forward(self)


if __name__ == "__main__":
    # Initializing Dependency Injection In IWA
    app = AppBootstrap()

    # IWA logging with loguru
    logger.remove()  # Remove default handler
    logger.add("logfile.log", level="INFO")  # Log to a file
    logger.add(lambda msg: print(msg, end=""), level="WARNING")  # Log to console

    with Validator() as validator:
        while True:
            bt.logging.info(f"Validator running... {time.time()}")
            time.sleep(5)
