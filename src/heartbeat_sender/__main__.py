#!/usr/bin/env python3

# Sends a heartbeat to AWS every hour so the watchdog knows the Pi is alive.
# Reachability of the Bitcoin node is checked independently by a Lambda on AWS.

import sys
import traceback

import requests

from .config import config


def check():
    post_heartbeat()


def post_heartbeat():
    cfg = config()
    endpoint = cfg["heartbeat"]["receiver"]["endpoint"]
    try:
        r = requests.post(endpoint, json={"source": "lasvegas"})
        if r.status_code not in (200, 201):
            print(f"Failed to send heartbeat:\nCode: {r.status_code}\nResult: {r.text}")
            return
        print("Heartbeat sent.")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send heartbeat: {e}")


def run():
    try:
        check()
    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    run()
