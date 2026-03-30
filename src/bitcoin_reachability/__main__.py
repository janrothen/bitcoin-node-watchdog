#!/usr/bin/env python3

# Sends a heartbeat to AWS every hour so the watchdog knows the Pi is alive.
# Reachability of the Bitcoin node is checked independently by a Lambda on AWS.

import sys
import traceback

from .utils.config import config
from .utils.request import Request


def check():
    post_heartbeat()


def post_heartbeat():
    cfg = config()
    endpoint = cfg["bitcoin"]["reachability"]["heartbeat_endpoint"]
    try:
        Request().post(endpoint, {"source": "lasvegas"})
        print("Heartbeat sent.")
    except ConnectionError as e:
        print(f"Failed to send heartbeat: {e}")


def run():
    try:
        check()
    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    run()
