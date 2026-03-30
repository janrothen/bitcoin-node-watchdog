import importlib.util
import socket
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

_LAMBDA = (
    Path(__file__).parent.parent / "aws/lambdas/reachability_checker/lambda_function.py"
)
spec = importlib.util.spec_from_file_location("reachability_checker", _LAMBDA)
lf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lf)

MAGIC = lf.MAGIC
VERACK = MAGIC + b"verack\x00\x00\x00\x00\x00\x00"
VERSION = MAGIC + b"version\x00\x00\x00\x00\x00"


# ── lambda_handler ────────────────────────────────────────────────────────────


@patch.object(lf, "_put_metric")
@patch.object(lf, "_check", return_value=True)
def test_lambda_handler_reachable(mock_check, mock_put):
    assert lf.lambda_handler({}, None) == {"reachable": True}
    mock_put.assert_called_once_with(True)


@patch.object(lf, "_put_metric")
@patch.object(lf, "_check", return_value=False)
def test_lambda_handler_unreachable(mock_check, mock_put):
    assert lf.lambda_handler({}, None) == {"reachable": False}
    mock_put.assert_called_once_with(False)


# ── _check ────────────────────────────────────────────────────────────────────


def _mock_conn(response: bytes):
    sock = MagicMock()
    sock.recv.return_value = response
    cm = MagicMock()
    cm.__enter__.return_value = sock
    cm.__exit__.return_value = False
    return cm


@patch.object(lf.socket, "create_connection")
@patch.object(lf.socket, "gethostbyname", return_value="1.2.3.4")
def test_check_verack(mock_dns, mock_conn):
    mock_conn.return_value = _mock_conn(VERACK + b"\x00" * 8)
    assert lf._check("test.duckdns.org", 8333) is True


@patch.object(lf.socket, "create_connection")
@patch.object(lf.socket, "gethostbyname", return_value="1.2.3.4")
def test_check_version_msg(mock_dns, mock_conn):
    mock_conn.return_value = _mock_conn(VERSION + b"\x00" * 100)
    assert lf._check("test.duckdns.org", 8333) is True


@patch.object(lf.socket, "gethostbyname", side_effect=socket.gaierror("DNS fail"))
def test_check_dns_error(mock_dns):
    assert lf._check("bad.hostname", 8333) is False


@patch.object(lf.socket, "create_connection", side_effect=ConnectionRefusedError)
@patch.object(lf.socket, "gethostbyname", return_value="1.2.3.4")
def test_check_connection_refused(mock_dns, mock_conn):
    assert lf._check("test.duckdns.org", 8333) is False


# ── _wait_for_verack ──────────────────────────────────────────────────────────


def test_wait_for_verack_finds_verack():
    sock = MagicMock()
    sock.recv.return_value = VERACK + b"\x00" * 8
    assert lf._wait_for_verack(sock) is True


def test_wait_for_verack_finds_version():
    sock = MagicMock()
    sock.recv.return_value = VERSION + b"\x00" * 100
    assert lf._wait_for_verack(sock) is True


def test_wait_for_verack_connection_closes():
    sock = MagicMock()
    sock.recv.return_value = b""
    assert lf._wait_for_verack(sock) is False


def test_wait_for_verack_garbage_fills_buffer():
    sock = MagicMock()
    sock.recv.side_effect = [b"x" * 256] * 16  # 16 × 256 = 4096 → loop exits
    assert lf._wait_for_verack(sock) is False


# ── _put_metric ───────────────────────────────────────────────────────────────


@patch.object(lf, "CLOUDWATCH")
def test_put_metric_reachable(mock_cw):
    lf._put_metric(True)
    metric = mock_cw.put_metric_data.call_args.kwargs["MetricData"][0]
    assert metric["Value"] == 1.0


@patch.object(lf, "CLOUDWATCH")
def test_put_metric_unreachable(mock_cw):
    lf._put_metric(False)
    metric = mock_cw.put_metric_data.call_args.kwargs["MetricData"][0]
    assert metric["Value"] == 0.0


# ── pure functions ────────────────────────────────────────────────────────────


def test_message_starts_with_magic():
    assert lf._message(b"version", b"payload")[:4] == MAGIC


def test_message_command_padded_to_12_bytes():
    msg = lf._message(b"version", b"payload")
    assert msg[4:16] == b"version\x00\x00\x00\x00\x00"


def test_net_addr_length():
    assert len(lf._net_addr("1.2.3.4", 8333)) == 26  # 8 + 16 + 2


def test_net_addr_port_big_endian():
    addr = lf._net_addr("1.2.3.4", 8333)
    assert struct.unpack(">H", addr[-2:])[0] == 8333
