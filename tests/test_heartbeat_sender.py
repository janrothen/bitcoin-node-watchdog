import hashlib
import hmac
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from heartbeat_sender.__main__ import HeartbeatSender, _from_env

ENDPOINT = "https://example.lambda-url.eu-north-1.on.aws/"
SECRET = "test-secret"
NODE_ID = "lasvegas"


@pytest.fixture
def sender() -> HeartbeatSender:
    return HeartbeatSender(endpoint=ENDPOINT, secret=SECRET, node_id=NODE_ID)


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


# ── HeartbeatSender.send ─────────────────────────────────────────────────────


@patch("heartbeat_sender.__main__.requests.post")
def test_send_success_200(mock_post, sender, capsys):
    mock_post.return_value = _mock_response(200)
    assert sender.send() is True

    call = mock_post.call_args
    assert call.args[0] == ENDPOINT
    body = call.kwargs["json"]
    assert body["source"] == NODE_ID
    assert "sent_at" in body
    expected_token = hmac.new(
        SECRET.encode(), body["sent_at"].encode(), hashlib.sha256
    ).hexdigest()
    assert call.kwargs["headers"]["X-Heartbeat-Signature-256"] == expected_token
    assert call.kwargs["timeout"] == 10
    assert "Heartbeat sent." in capsys.readouterr().out


@patch("heartbeat_sender.__main__.requests.post")
def test_send_success_201(mock_post, sender, capsys):
    mock_post.return_value = _mock_response(201)
    assert sender.send() is True
    assert "Heartbeat sent." in capsys.readouterr().out


@patch("heartbeat_sender.__main__.requests.post")
def test_send_bad_status(mock_post, sender, capsys):
    mock_post.return_value = _mock_response(500, "Internal Server Error")
    assert sender.send() is False
    out = capsys.readouterr().out
    assert "Failed to send heartbeat" in out
    assert "500" in out


@patch(
    "heartbeat_sender.__main__.requests.post",
    side_effect=requests.exceptions.ConnectionError("boom"),
)
def test_send_connection_error(mock_post, sender, capsys):
    assert sender.send() is False
    assert "Failed to send heartbeat" in capsys.readouterr().out


@patch(
    "heartbeat_sender.__main__.requests.post",
    side_effect=requests.exceptions.Timeout("timed out"),
)
def test_send_timeout(mock_post, sender, capsys):
    assert sender.send() is False
    assert "Failed to send heartbeat" in capsys.readouterr().out


@patch("heartbeat_sender.__main__.requests.post")
def test_send_uses_timezone_aware_timestamp(mock_post, sender):
    mock_post.return_value = _mock_response(200)
    sender.send()

    body = mock_post.call_args.kwargs["json"]
    dt = datetime.fromisoformat(body["sent_at"])
    assert dt.tzinfo is not None


@patch("heartbeat_sender.__main__.requests.post")
def test_send_respects_custom_timeout(mock_post):
    mock_post.return_value = _mock_response(200)
    HeartbeatSender(ENDPOINT, SECRET, NODE_ID, timeout=3).send()
    assert mock_post.call_args.kwargs["timeout"] == 3


# ── _sign ────────────────────────────────────────────────────────────────────


def test_sign_matches_expected_hmac():
    sent_at = "2026-04-19T12:00:00+00:00"
    expected = hmac.new(SECRET.encode(), sent_at.encode(), hashlib.sha256).hexdigest()
    assert HeartbeatSender._sign(SECRET, sent_at) == expected


# ── _from_env ────────────────────────────────────────────────────────────────


@patch(
    "heartbeat_sender.__main__.config",
    return_value={"heartbeat": {"receiver": {"endpoint": ENDPOINT}}},
)
@patch.dict(os.environ, {"HEARTBEAT_SECRET": SECRET, "NODE_ID": NODE_ID})
def test_from_env_wires_config_and_env(mock_config):
    s = _from_env()
    assert s._endpoint == ENDPOINT
    assert s._secret == SECRET
    assert s._node_id == NODE_ID
