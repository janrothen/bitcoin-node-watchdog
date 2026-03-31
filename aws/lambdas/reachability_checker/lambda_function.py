import hashlib
import os
import socket
import struct
import time

import boto3

MAGIC = b"\xf9\xbe\xb4\xd9"  # Bitcoin mainnet magic bytes
CLOUDWATCH = boto3.client("cloudwatch")
NAMESPACE = "BitcoinNode"
DIMENSION = {"Name": "NodeId", "Value": os.environ["NODE_ID"]}


def lambda_handler(event, context):
    hostname = os.environ["DUCKDNS_HOSTNAME"]
    port = int(os.environ.get("BITCOIN_PORT", "8333"))
    reachable = _check(hostname, port)
    _put_metric(reachable)
    return {"reachable": reachable}


def _check(hostname: str, port: int) -> bool:
    try:
        ip = socket.gethostbyname(hostname)
        with socket.create_connection((ip, port), timeout=10) as sock:
            sock.sendall(_version_message(ip, port))
            return _wait_for_verack(sock)
    except Exception as e:
        print(f"Reachability check failed: {e}")
        return False


def _version_message(ip: str, port: int) -> bytes:
    version = 70015
    services = 1
    timestamp = int(time.time())
    addr_recv = _net_addr(ip, port)
    addr_from = _net_addr("0.0.0.0", 0)
    nonce = struct.pack("<Q", int.from_bytes(os.urandom(8), "little"))
    user_agent_str = b"/Satoshi:30.2.0/"
    user_agent = bytes([len(user_agent_str)]) + user_agent_str
    start_height = struct.pack("<i", 0)

    payload = (
        struct.pack("<i", version)
        + struct.pack("<Q", services)
        + struct.pack("<q", timestamp)
        + addr_recv
        + addr_from
        + nonce
        + user_agent
        + start_height
    )
    return _message(b"version", payload)


def _net_addr(ip: str, port: int) -> bytes:
    services = struct.pack("<Q", 1)
    ip_bytes = b"\x00" * 10 + b"\xff\xff" + socket.inet_aton(ip)
    port_bytes = struct.pack(">H", port)
    return services + ip_bytes + port_bytes


def _message(command: bytes, payload: bytes) -> bytes:
    cmd = command.ljust(12, b"\x00")
    length = struct.pack("<I", len(payload))
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return MAGIC + cmd + length + checksum + payload


def _wait_for_verack(sock: socket.socket) -> bool:
    sock.settimeout(10)
    buf = b""
    # Read until we find a verack or give up after 4096 bytes.
    # Bounded by the 10s socket timeout even if the remote sends continuous garbage.
    while len(buf) < 4096:
        chunk = sock.recv(256)
        if not chunk:
            break
        buf += chunk
        # Scan for verack message header (magic + "verack\x00\x00\x00\x00\x00\x00")
        verack_cmd = MAGIC + b"verack\x00\x00\x00\x00\x00\x00"
        if verack_cmd in buf:
            return True
        # Also accept if we got a version message back (node is alive and talking)
        version_cmd = MAGIC + b"version\x00\x00\x00\x00\x00"
        if version_cmd in buf:
            return True
    return False


def _put_metric(reachable: bool) -> None:
    CLOUDWATCH.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[
            {
                "MetricName": "NodeReachable",
                "Dimensions": [DIMENSION],
                "Value": 1.0 if reachable else 0.0,
                "Unit": "Count",
            }
        ],
    )
