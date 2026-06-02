from __future__ import annotations

import sys

from autoppia_web_agents_subnet.miner.cli import cli


def main() -> None:
    cli.main(args=sys.argv[1:], prog_name="miner-cli", standalone_mode=True)


if __name__ == "__main__":
    main()
