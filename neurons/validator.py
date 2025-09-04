import sys
import time
from pathlib import Path

# If this keep working without this delete it!
# sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bittensor as bt
from autoppia_web_agents_subnet.base.validator import BaseValidatorNeuron
from autoppia_web_agents_subnet.validator.forward import forward
from autoppia_web_agents_subnet.base.utils.config import config
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

    # IWA logging works with loguru
    logger.remove()  # Remove default handler
    logger.add("logfile.log", level="INFO")  # Log to a file
    logger.add(lambda msg: print(msg, end=""), level="WARNING")  # Log to console

    with Validator(config=config(role="validator")) as validator:
        while True:
            bt.logging.info(f"Validator running... {time.time()}")
            time.sleep(5)
