import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import requests

from heartbeat_sender.__main__ import post_heartbeat

ENDPOINT = "https://example.lambda-url.eu-north-1.on.aws/"

CONFIG = {"heartbeat": {"receiver": {"endpoint": ENDPOINT}}}

_ENV = {"HEARTBEAT_SECRET": "test-secret"}


def _mock_response(status_code, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


@patch("heartbeat_sender.__main__.requests.post")
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
@patch.dict(os.environ, _ENV)
def test_post_heartbeat_success_200(mock_config, mock_post, capsys):
    mock_post.return_value = _mock_response(200)
    post_heartbeat()

    call = mock_post.call_args
    assert call.args[0] == ENDPOINT
    assert call.kwargs["json"]["source"] == "lasvegas"
    assert "sent_at" in call.kwargs["json"]
    assert call.kwargs["headers"]["X-Heartbeat-Token"] == "test-secret"
    assert "Heartbeat sent." in capsys.readouterr().out


@patch("heartbeat_sender.__main__.requests.post")
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
@patch.dict(os.environ, _ENV)
def test_post_heartbeat_success_201(mock_config, mock_post, capsys):
    mock_post.return_value = _mock_response(201)
    post_heartbeat()
    assert "Heartbeat sent." in capsys.readouterr().out


@patch("heartbeat_sender.__main__.requests.post")
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
@patch.dict(os.environ, _ENV)
def test_post_heartbeat_bad_status(mock_config, mock_post, capsys):
    mock_post.return_value = _mock_response(500, "Internal Server Error")
    post_heartbeat()
    out = capsys.readouterr().out
    assert "Failed to send heartbeat" in out
    assert "500" in out


@patch(
    "heartbeat_sender.__main__.requests.post",
    side_effect=requests.exceptions.ConnectionError("timeout"),
)
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
@patch.dict(os.environ, _ENV)
def test_post_heartbeat_connection_error(mock_config, mock_post, capsys):
    post_heartbeat()
    assert "Failed to send heartbeat" in capsys.readouterr().out


@patch(
    "heartbeat_sender.__main__.requests.post",
    side_effect=requests.exceptions.Timeout("timed out"),
)
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
@patch.dict(os.environ, _ENV)
def test_post_heartbeat_timeout(mock_config, mock_post, capsys):
    post_heartbeat()
    assert "Failed to send heartbeat" in capsys.readouterr().out


@patch("heartbeat_sender.__main__.requests.post")
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
@patch.dict(os.environ, _ENV)
def test_post_heartbeat_sends_auth_header_and_timestamp(mock_config, mock_post):
    mock_post.return_value = _mock_response(200)
    post_heartbeat()

    call = mock_post.call_args
    headers = call.kwargs["headers"]
    body = call.kwargs["json"]

    assert headers["X-Heartbeat-Token"] == "test-secret"
    assert "sent_at" in body
    dt = datetime.fromisoformat(body["sent_at"])
    assert dt.tzinfo is not None  # must be timezone-aware
