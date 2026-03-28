#!/usr/bin/env python3

# Checks if the Bitcoin full node is reachable from outside via bitnodes.io.
# If reachable, posts a heartbeat to AWS. The AWS watchdog Lambda alerts
# when heartbeats stop arriving (catches Pi/network/node outages).

import json
import sys
import traceback

from .utils.config import config
from .utils.request import Request


def check():
    if is_reachable():
        post_heartbeat()
    else:
        print("Node is not reachable from outside.")


def is_reachable():
    cfg = config()
    endpoint = cfg["bitcoin"]["reachability"]["service_endpoint"]
    try:
        result = Request().get(endpoint)
        return json.loads(result).get("success", False)
    except ConnectionError:
        return False


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
