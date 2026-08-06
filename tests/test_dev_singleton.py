"""Local single-instance port helper."""

from __future__ import annotations

from game.dev_singleton import pids_listening_on_port


def test_pids_listening_on_port_parses_english_netstat():
    sample = """
  TCP    127.0.0.1:5000         0.0.0.0:0              LISTENING       15184
  TCP    127.0.0.1:5000         127.0.0.1:49207        TIME_WAIT       0
  TCP    0.0.0.0:5001           0.0.0.0:0              LISTENING       99
"""
    assert pids_listening_on_port(5000, netstat_output=sample) == {15184}
    assert pids_listening_on_port(5001, netstat_output=sample) == {99}
    assert pids_listening_on_port(9999, netstat_output=sample) == set()


def test_pids_listening_on_port_parses_german_listen_state():
    sample = """
  TCP    127.0.0.1:5000         0.0.0.0:0              ABHÖREN         4242
  TCP    127.0.0.1:5000         127.0.0.1:1            WARTEND         0
"""
    assert pids_listening_on_port(5000, netstat_output=sample) == {4242}
