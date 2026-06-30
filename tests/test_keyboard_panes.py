"""Tests for Ctrl+N pane keyboard tokens."""

from cli.keyboard_input import PANE_1, PANE_2, poll_stdin_event


def test_ctrl_digit_maps_to_pane_token(monkeypatch):
    monkeypatch.setattr(
        "cli.keyboard_input._read_stdin_chunk",
        lambda _timeout: "\x02",
    )
    assert poll_stdin_event(0.1) == PANE_2


def test_ctrl_one_maps_to_pane_1(monkeypatch):
    monkeypatch.setattr(
        "cli.keyboard_input._read_stdin_chunk",
        lambda _timeout: "\x01",
    )
    assert poll_stdin_event(0.1) == PANE_1
