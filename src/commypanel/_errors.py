"""Errors raised by the client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover
    from ._types import Deployment


class CommyPanelError(Exception):
    """Base class of everything this library raises on purpose."""


class InsecureURLError(CommyPanelError):
    """The panel address is not https (or loopback http, when allowed)."""


class InvalidURLError(CommyPanelError):
    """The panel address is not a plain scheme://host[:port]."""


class InvalidTokenError(CommyPanelError):
    """The token is empty, too long, or has spaces or control characters."""


class InvalidInputError(CommyPanelError):
    """An app name or variable name that cannot be valid; no request was made."""


class ResponseTooLargeError(CommyPanelError):
    """An answer is bigger than the client accepts."""


class RedirectError(CommyPanelError):
    """The panel answered with a redirect. Redirects are never followed, so a token cannot be handed to another address."""


class TransportError(CommyPanelError):
    """The request could not be made or answered (connection, TLS, timeout)."""


class WaitTimeoutError(CommyPanelError):
    """wait_for_deployment gave up waiting; the deployment itself carries on in the panel."""


class ApiError(CommyPanelError):
    """An error answer from the panel."""

    def __init__(
        self,
        status: int,
        message: str,
        fields: Optional[Dict[str, List[str]]] = None,
        deployment: "Optional[Deployment]" = None,
        retry_after_seconds: int = 0,
    ) -> None:
        super().__init__(status, message)
        self.status = status
        #: The panel's own sentence (its ``error`` key).
        self.message = message
        #: The problems of a 422, by field name.
        self.fields: Dict[str, List[str]] = dict(fields or {})
        #: The deployment that is already running, on a 409 that says so.
        self.deployment = deployment
        #: How long the panel asked to wait, when it did (429), in seconds.
        self.retry_after_seconds = retry_after_seconds

    def __str__(self) -> str:
        text = "commypanel: %d %s" % (self.status, self.message)

        for name in sorted(self.fields):
            text += " (%s: %s)" % (name, " ".join(self.fields[name]))

        return text


def _has_status(err: BaseException, status: int) -> bool:
    return isinstance(err, ApiError) and err.status == status


def is_not_found(err: BaseException) -> bool:
    """A 404: no such app, deployment or variable, or an app the token may not use."""
    return _has_status(err, 404)


def is_unauthorized(err: BaseException) -> bool:
    """A 401: no token, or an invalid, revoked or expired one."""
    return _has_status(err, 401)


def is_forbidden(err: BaseException) -> bool:
    """A 403: the token lacks the ability, or its owner lacks the permission."""
    return _has_status(err, 403)


def is_conflict(err: BaseException) -> bool:
    """A 409: the state does not allow it, for example a deployment is already running (see ``ApiError.deployment``)."""
    return _has_status(err, 409)


def is_rate_limited(err: BaseException) -> bool:
    """A 429."""
    return _has_status(err, 429)
