from unittest.mock import MagicMock, patch

from heartbeat_sender.__main__ import post_heartbeat

ENDPOINT = "https://example.lambda-url.eu-north-1.on.aws/"

CONFIG = {"heartbeat": {"receiver": {"endpoint": ENDPOINT}}}


def _mock_response(status_code, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


@patch("heartbeat_sender.__main__.requests.post")
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
def test_post_heartbeat_success_200(mock_config, mock_post, capsys):
    mock_post.return_value = _mock_response(200)
    post_heartbeat()
    mock_post.assert_called_once_with(ENDPOINT, json={"source": "lasvegas"})
    assert "Heartbeat sent." in capsys.readouterr().out


@patch("heartbeat_sender.__main__.requests.post")
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
def test_post_heartbeat_success_201(mock_config, mock_post, capsys):
    mock_post.return_value = _mock_response(201)
    post_heartbeat()
    assert "Heartbeat sent." in capsys.readouterr().out


@patch("heartbeat_sender.__main__.requests.post")
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
def test_post_heartbeat_bad_status(mock_config, mock_post, capsys):
    mock_post.return_value = _mock_response(500, "Internal Server Error")
    post_heartbeat()
    out = capsys.readouterr().out
    assert "Failed to send heartbeat" in out
    assert "500" in out


@patch(
    "heartbeat_sender.__main__.requests.post", side_effect=ConnectionError("timeout")
)
@patch("heartbeat_sender.__main__.config", return_value=CONFIG)
def test_post_heartbeat_connection_error(mock_config, mock_post, capsys):
    post_heartbeat()
    assert "Failed to send heartbeat" in capsys.readouterr().out
