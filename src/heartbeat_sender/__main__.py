#!/usr/bin/env python3

# Sends a heartbeat to AWS every hour so the watchdog knows the Pi is alive.
# Reachability of the Bitcoin node is checked independently by a Lambda on AWS.

import os
import sys
import traceback

from .config import config
from .sender import HeartbeatSender


def _from_env() -> HeartbeatSender:
    cfg = config()
    return HeartbeatSender(
        endpoint=cfg["heartbeat"]["receiver"]["endpoint"],
        secret=os.environ["HEARTBEAT_SECRET"],
        node_id=os.environ["NODE_ID"],
    )


def run() -> None:
    try:
        if not _from_env().send():
            sys.exit(1)
    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    run()
