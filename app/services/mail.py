"""Outbound email.

This build has no SMTP credentials, so messages are recorded in the application
log rather than sent. That is a deliberate, visible limitation — not a silent
failure: :func:`deliver` always logs the recipient, subject and body, and the
single place a real transport plugs in is documented below.

To send for real, install Flask-Mail (``pip install flask-mail``) and replace the
body of :func:`_send` with a ``Message``/``mail.send`` call. Every caller keeps
working unchanged because they all go through :func:`deliver`.

What is deliberately *not* done here: no credential is read at import time and no
message is silently swallowed. If a transport is configured and raises, the error
propagates to the caller's error handling rather than disappearing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from flask import current_app

logger = logging.getLogger("jobhunter.mail")


@dataclass(frozen=True)
class Message:
    """One outbound email."""

    to: str
    subject: str
    body: str
    #: Free-form provenance for the log line, e.g. ("job_alert", 12).
    tags: dict = field(default_factory=dict)


def _send(message: Message) -> None:
    """Transport seam.

    Replace this single function to send real email. With no SMTP configured the
    app logs instead of sending, which keeps the whole codebase runnable offline.
    """
    current_app.logger.info(
        "[email:logged-not-sent] to=%s subject=%s%s\n%s",
        message.to,
        message.subject,
        f" tags={message.tags}" if message.tags else "",
        message.body,
    )


def deliver(message: Message) -> Message:
    """Send a message. Returns it so callers can log or queue the result."""
    if not message.to:
        raise ValueError("refusing to send an email with no recipient")
    _send(message)
    return message
