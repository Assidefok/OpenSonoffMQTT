"""Logging behaviour of the MQTT client wrapper."""

import logging

from app.mqtt_client import MQTTClient


def test_unexpected_disconnect_is_a_warning(caplog):
    client = MQTTClient("127.0.0.1")

    with caplog.at_level(logging.DEBUG):
        client._handle_disconnect(None, None)

    assert client.connected is False
    assert any(
        record.levelno == logging.WARNING
        and "retrying in the background" in record.getMessage()
        for record in caplog.records
    )


def test_stopping_disconnect_stays_in_debug(caplog):
    client = MQTTClient("127.0.0.1")
    client._stopping = True

    with caplog.at_level(logging.DEBUG):
        client._handle_disconnect(None, None)

    assert client.connected is False
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("(stop)" in record.getMessage() for record in caplog.records)
