"""Ordinary tests cannot acquire models or data over the network."""

import os
from collections.abc import Iterator
from typing import Never

import pytest


@pytest.fixture(autouse=True)
def private_artifact_umask() -> Iterator[None]:
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> Never:
        raise AssertionError("network is forbidden in ordinary unit tests")

    monkeypatch.setattr("socket.create_connection", denied)
    monkeypatch.setattr("socket.socket.connect", denied)
