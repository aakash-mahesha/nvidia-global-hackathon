"""The event bus — the ONLY module in this repo that imports an MQTT client.

`docs/CONTRACTS.md` §3: publishers and subscribers depend only on the topic
strings and the JSON payloads, never on a broker-specific API. That rule is
enforced here by construction — everything else in the codebase says:

    from evtol.bus import Bus
    from evtol.messages import RigState
    from evtol.topics import TOPIC_RIG_STATE

    with Bus() as bus:
        bus.publish(TOPIC_RIG_STATE, state)          # takes a typed model
        bus.subscribe(TOPIC_RIG_STATE, on_state)     # hands back a typed model

and never sees a client, a QoS flag or a byte string. If MQTT turns out to be
the wrong choice in week 3, swapping it is this one file.

Two behaviours worth knowing:

* **Everything is validated at the boundary.** Outbound messages are models
  already; inbound bytes are parsed through `evtol.messages.decode` before a
  handler sees them. A malformed message never reaches application code — it
  goes to `on_error` instead.
* **Subscriptions survive reconnects.** They are recorded and re-issued on
  every connect, so a broker restart does not silently leave the console
  subscribed to nothing. On a rig where the bus IS the API, a subscriber that
  quietly stops receiving is indistinguishable from a rig that stopped moving.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional
from urllib.parse import urlparse

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from evtol.config import Settings, load_settings
from evtol.messages import BusMessage, decode, encode
from evtol.topics import (
    TOPIC_CLOCK_TURNAROUND,
    TOPIC_MONITOR_VERDICT,
    TOPIC_PERMIT_DECISION,
    TOPIC_RIG_INTERLOCK,
    TOPIC_RIG_STATE,
)

log = logging.getLogger(__name__)

DEFAULT_PORT = 1883
CONNECT_TIMEOUT_S = 5.0

# QoS per topic (docs/CONTRACTS.md §3, PROPOSED pending ratification).
#
# QoS 0 — fire and forget — for high-rate telemetry. At 20-25 Hz a dropped
# frame is replaced 50 ms later; paying for delivery guarantees on a stream
# that is obsolete on arrival buys nothing.
#
# QoS 1 — at least once — for anything a DECISION hangs on. An interlock
# transition or a permit refusal that goes missing is not self-correcting:
# the console would keep showing the previous state indefinitely.
QOS_FOR_TOPIC: dict[str, int] = {
    TOPIC_RIG_STATE: 0,
    TOPIC_MONITOR_VERDICT: 0,
    TOPIC_CLOCK_TURNAROUND: 0,
    TOPIC_RIG_INTERLOCK: 1,
    TOPIC_PERMIT_DECISION: 1,
}

# Never retain. A reconnecting subscriber must see live state or nothing —
# a retained message would show the console a rig that has since been powered
# off, which is the most dangerous possible lie for this system to tell.
RETAIN = False

Handler = Callable[[BusMessage], None]
ErrorHandler = Callable[[str, bytes, Exception], None]


def _log_bad_message(topic: str, payload: bytes, exc: Exception) -> None:
    """Default on_error: drop the message loudly, keep the bus alive.

    One malformed publisher must not take down every subscriber — but it must
    also never pass silently, or a field-name typo becomes a dashboard that
    renders nothing for a week.
    """
    log.error("undecodable message on %s (%d bytes): %s", topic, len(payload), exc)


class BusError(RuntimeError):
    """Raised when the bus cannot be reached or is misconfigured."""


class Bus:
    """A connection to the event bus.

    url       — `mqtt://host:port`. Defaults to EVENT_BUS_URL from the
                layered config (.env.shared < .env < environment).
    client_id — shows up in broker logs; make it identifiable ("console",
                "rig-mock", "monitor") so `connection_messages` output in
                infra/mosquitto.conf is actually useful during integration.
    on_error  — called with (topic, raw_payload, exception) when an inbound
                message fails validation.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        client_id: Optional[str] = None,
        settings: Optional[Settings] = None,
        on_error: ErrorHandler = _log_bad_message,
    ) -> None:
        if url is None:
            settings = settings or load_settings(strict=False)
            url = settings.event_bus_url
        if not url:
            raise BusError(
                "EVENT_BUS_URL is not set. Put it in your .env "
                "(mqtt://127.0.0.1:1883 for a local broker — start one with "
                "`mosquitto -c infra/mosquitto.conf -v`). See docs/SETUP.md §9."
            )

        self.url = url
        self.host, self.port = self._parse(url)
        self.on_error = on_error

        # Subscriptions are kept so they can be re-issued on every (re)connect.
        self._handlers: dict[str, list[Handler]] = {}
        self._connected = threading.Event()

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id or "",
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # --- lifecycle ----------------------------------------------------------

    @staticmethod
    def _parse(url: str) -> tuple[str, int]:
        parsed = urlparse(url)
        if parsed.scheme != "mqtt":
            raise BusError(
                f"EVENT_BUS_URL must start with mqtt:// (got {url!r}). "
                "The broker is MQTT/mosquitto — see docs/DECISIONS.md D-002."
            )
        if not parsed.hostname:
            raise BusError(f"no host in EVENT_BUS_URL {url!r}")
        return parsed.hostname, parsed.port or DEFAULT_PORT

    def connect(self) -> "Bus":
        try:
            self._client.connect(self.host, self.port)
        except OSError as e:
            raise BusError(
                f"cannot reach the broker at {self.host}:{self.port} — {e}. "
                "Is mosquitto running? `mosquitto -c infra/mosquitto.conf -v`"
            ) from e
        self._client.loop_start()
        if not self._connected.wait(CONNECT_TIMEOUT_S):
            self.close()
            raise BusError(
                f"connected to {self.host}:{self.port} but the broker never "
                f"acknowledged within {CONNECT_TIMEOUT_S}s"
            )
        return self

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        self._connected.clear()

    def __enter__(self) -> "Bus":
        return self.connect()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- the API everything else uses ---------------------------------------

    def publish(self, topic: str, message: BusMessage) -> None:
        """Publish a typed message. QoS and retain come from the contract."""
        info = self._client.publish(
            topic,
            payload=encode(message),
            qos=QOS_FOR_TOPIC.get(topic, 0),
            retain=RETAIN,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise BusError(f"publish to {topic} failed: {mqtt.error_string(info.rc)}")

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Register a handler. It receives a validated model, never bytes.

        Safe to call before connect(); subscriptions are (re)issued on every
        connect, so a broker restart does not leave you silently unsubscribed.
        """
        self._handlers.setdefault(topic, []).append(handler)
        if self._connected.is_set():
            self._client.subscribe(topic, qos=QOS_FOR_TOPIC.get(topic, 0))

    # --- paho callbacks (nothing outside this file should see these) --------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code != 0:
            log.error("broker refused the connection: %s", reason_code)
            return
        self._connected.set()
        for topic in self._handlers:
            client.subscribe(topic, qos=QOS_FOR_TOPIC.get(topic, 0))
        log.info(
            "connected to %s:%d, subscribed to %s",
            self.host,
            self.port,
            sorted(self._handlers) or "nothing",
        )

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        self._connected.clear()
        log.warning("disconnected from %s:%d (%s)", self.host, self.port, reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            message = decode(msg.topic, msg.payload)
        except (ValidationError, ValueError) as e:
            self.on_error(msg.topic, msg.payload, e)
            return
        for handler in self._handlers.get(msg.topic, []):
            try:
                handler(message)
            except Exception:  # noqa: BLE001 — one bad handler must not kill the loop
                log.exception("handler for %s raised", msg.topic)
