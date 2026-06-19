"""
Tokinarc V6.C-fix — tokinarc/eventbus/listener.py

Long-running process subscribe LISTEN/NOTIFY. Chạy bởi worker container
(infra/scripts/worker_entrypoint.sh).

Pattern subscribe handler:

    @subscribe(Channel.ORDER_CREATED)
    def on_order_created(payload: dict) -> None:
        ...

Khi listener crash khi handle, log + ghi `EventDeadLetter` (B.5 §2.4) để
retry sau, KHÔNG để mất event.
"""
from __future__ import annotations

import json
import logging
import select
import time
from typing import Callable

from django.db import connection

from .channels import ALL_CHANNELS

logger = logging.getLogger(__name__)

_HANDLERS: dict[str, list[Callable[[dict], None]]] = {}


def subscribe(channel: str):
    """Decorator đăng ký handler cho channel."""
    if channel not in ALL_CHANNELS:
        raise ValueError(f"Channel '{channel}' không trong registry.")

    def _decorator(fn: Callable[[dict], None]):
        _HANDLERS.setdefault(channel, []).append(fn)
        logger.info("handler_registered",
                    extra={"channel": channel, "handler": fn.__name__})
        return fn
    return _decorator


def _dispatch(channel: str, payload: dict) -> None:
    handlers = _HANDLERS.get(channel, [])
    for h in handlers:
        try:
            h(payload)
        except Exception as e:
            logger.exception("handler_failed", extra={
                "channel": channel, "handler": h.__name__, "error": str(e),
            })
            try:
                from apps.learning.models import EventDeadLetter
                EventDeadLetter.objects.create(
                    channel=channel, payload=payload, error=str(e),
                )
            except Exception:
                logger.error("dead_letter_save_failed")


def run_listener(channels: list[str] | None = None,
                 poll_timeout: float = 5.0) -> None:
    """
    Block-loop listen. Gọi từ management command hoặc entrypoint script.

    Args:
        channels: list channel để LISTEN; None = subscribe channels có handler
        poll_timeout: giây — interval check connection healthy
    """
    channels = channels or list(_HANDLERS.keys())
    if not channels:
        logger.warning("listener_no_channels — không có handler nào đăng ký")
        return

    raw = connection.cursor().connection  # psycopg connection
    raw.autocommit = True
    cur = raw.cursor()
    for ch in channels:
        cur.execute(f'LISTEN "{ch}";')   # quoted = case-sensitive; channels luôn lowercase
    logger.info("listener_started", extra={"channels": channels})

    try:
        while True:
            if select.select([raw], [], [], poll_timeout) == ([], [], []):
                continue   # timeout, loop again để check connection
            raw.poll()
            while raw.notifies:
                notify = raw.notifies.pop(0)
                try:
                    payload = json.loads(notify.payload) if notify.payload else {}
                except json.JSONDecodeError:
                    logger.warning("invalid_json_payload",
                                   extra={"channel": notify.channel, "raw": notify.payload[:200]})
                    continue
                logger.info("event_received",
                            extra={"channel": notify.channel, "pid": notify.pid})
                _dispatch(notify.channel, payload)
    except KeyboardInterrupt:
        logger.info("listener_stopped_by_signal")
    finally:
        cur.close()
