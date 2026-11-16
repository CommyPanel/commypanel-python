"""The client: one panel, one token."""

from __future__ import annotations

import http
import http.client
import ipaddress
import json
import socket
import ssl
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

from ._errors import (
    ApiError,
    CommyPanelError,
    InsecureURLError,
    InvalidInputError,
    InvalidTokenError,
    InvalidURLError,
    RedirectError,
    ResponseTooLargeError,
    TransportError,
    WaitTimeoutError,
)
from ._types import App, Deployment, EnvChange, EnvKeys, Logs, Token
from ._validate import check_env_key, check_number, check_slug

__version__ = "0.1.0"

_BASE_PATH = "/api/v1"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_BODY = 16 << 20  # 16 MiB: far more than 5000 log lines
_MAX_ERROR_BODY = 1 << 20
_DEFAULT_RETRIES = 2
_MAX_RETRIES = 5
_MAX_RETRY_WAIT = 30.0


class Client:
    """A client for one CommyPanel server with one token. It keeps no per-call state, so it can be shared between threads.

    Args:
        base_url: The panel address, ``https://panel.example.com``.
        token: An API token (Settings > API tokens in the panel).
        allow_http_loopback: Allow plain http, but only for localhost, 127.0.0.1 or ::1 (development).
        ca_cert_pem: One more certificate authority to trust, in PEM, besides the system's, for a panel with a
            private CA. There is deliberately no option to skip verification.
        timeout: Seconds one network operation may take (default 30).
        retries: How many times a failed request may be tried again (default 2, at most 5). Only requests that
            are safe to repeat are retried: any request the panel refused with 429, and reading calls that met
            a 502, 503 or 504.
        max_response_bytes: The largest answer the client will read (default 16 MiB).
        user_agent: A name (your tool) to put in front of the library's User-Agent.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        allow_http_loopback: bool = False,
        ca_cert_pem: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        retries: int = _DEFAULT_RETRIES,
        max_response_bytes: int = _DEFAULT_MAX_BODY,
        user_agent: Optional[str] = None,
    ) -> None:
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("commypanel: the timeout must be positive")

        if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= _MAX_RETRIES:
            raise ValueError("commypanel: retries must be between 0 and 5")

        if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool) or max_response_bytes <= 0:
            raise ValueError("commypanel: the limit must be positive")

        scheme, netloc, host, port = _check_base_url(base_url, allow_http_loopback)
        _check_token(token)

        self._scheme = scheme
        self._netloc = netloc
        self._host = host
        self._port = port
        self._token = token
        self._timeout = float(timeout)
        self._retries = retries
        self._max_body = max_response_bytes
        self._agent = "commypanel-python/" + __version__
        self._ssl = _tls_context(ca_cert_pem) if scheme == "https" else None

        if user_agent and user_agent.strip():
            self._agent = user_agent.strip() + " " + self._agent

        #: Replaced in tests, so they do not really wait.
        self._sleep: Callable[[float], None] = time.sleep

    # -- the token never shows ------------------------------------------------------------

    def __repr__(self) -> str:
        return "Client(base_url=%r, token=<redacted>)" % self.base_url

    __str__ = __repr__

    def __getstate__(self) -> Any:
        raise TypeError("commypanel.Client holds a token and cannot be pickled or copied by value")

    @property
    def base_url(self) -> str:
        """The panel address the client uses."""
        return "%s://%s" % (self._scheme, self._netloc)

    # -- the API --------------------------------------------------------------------------

    def token(self) -> Token:
        """The token this client uses: its name, abilities, the apps it is limited to and when it expires.

        Any valid token may ask. It is a good way to check a token when it is saved.
        """
        _, data = self._request("GET", "/token")

        return Token.from_dict(_as_dict(data))

    def list_apps(self) -> List[App]:
        """The apps the token may see (ability ``apps:read``)."""
        _, data = self._request("GET", "/apps")

        return [App.from_dict(_as_dict(item)) for item in _as_list(data)]

    def get_app(self, slug: str) -> App:
        """One app (ability ``apps:read``)."""
        _, data = self._request("GET", _app_path(slug))

        return App.from_dict(_as_dict(data))

    def list_deployments(self, slug: str, limit: Optional[int] = None) -> List[Deployment]:
        """The newest deployments of an app, newest first (ability ``apps:read``).

        ``limit`` None uses the panel's default (20); the panel allows at most 50.
        """
        query = {"limit": str(limit)} if limit else None
        _, data = self._request("GET", _app_path(slug, "deployments"), query)

        return [Deployment.from_dict(_as_dict(item)) for item in _as_list(data)]

    def get_deployment(self, slug: str, number: int, with_log: bool = False) -> Deployment:
        """One deployment (ability ``apps:read``), with the build log when ``with_log`` is true."""
        check_number(number)
        query = {"log": "1"} if with_log else None
        _, data = self._request("GET", _app_path(slug, "deployments", str(number)), query)

        return Deployment.from_dict(_as_dict(data))

    def start_deployment(self, slug: str) -> Deployment:
        """Queue a deployment (ability ``apps:deploy``) and return it at once; follow it with ``wait_for_deployment``.

        If one is already running the error is a conflict (``is_conflict``) whose ``ApiError.deployment`` is the running one.
        """
        _, data = self._request("POST", _app_path(slug, "deployments"))

        return Deployment.from_dict(_as_dict(data))

    def apply_changes(self, slug: str) -> Deployment:
        """Make changed variables, volumes and links take effect from the running version, with no build (ability ``apps:deploy``)."""
        _, data = self._request("POST", _app_path(slug, "apply"))

        return Deployment.from_dict(_as_dict(data))

    def start_app(self, slug: str) -> App:
        """Start a stopped app (ability ``apps:control``)."""
        return self._control(slug, "start")

    def stop_app(self, slug: str) -> App:
        """Stop a running app; visitors see an error until it is started again (ability ``apps:control``)."""
        return self._control(slug, "stop")

    def restart_app(self, slug: str) -> App:
        """Restart a running app (ability ``apps:control``)."""
        return self._control(slug, "restart")

    def logs(self, slug: str, tail: Optional[int] = None) -> Logs:
        """The last lines of the running container's output (ability ``apps:logs``).

        ``tail`` is clamped by the panel to 10..5000 (default 200). Logs often hold secrets, and every read is
        recorded in the panel's audit log.
        """
        query = {"tail": str(tail)} if tail else None
        _, data = self._request("GET", _app_path(slug, "logs"), query)

        return Logs.from_dict(_as_dict(data))

    def list_env(self, slug: str) -> EnvKeys:
        """The names of an app's environment variables (ability ``apps:env``). The API never returns values."""
        _, data = self._request("GET", _app_path(slug, "env"))

        return EnvKeys.from_dict(_as_dict(data))

    def set_env(self, slug: str, key: str, value: str) -> Tuple[EnvChange, bool]:
        """Set an environment variable (ability ``apps:env``). Returns ``(change, created)``.

        The change takes effect with ``apply_changes`` or the next deployment. The value is sent, never read back.
        """
        check_env_key(key)
        path = _app_path(slug, "env", key)

        if not isinstance(value, str):
            raise InvalidInputError("commypanel: a variable's value must be a string")

        status, data = self._request("PUT", path, None, {"value": value})

        return EnvChange.from_dict(_as_dict(data)), status == 201

    def unset_env(self, slug: str, key: str) -> EnvChange:
        """Remove an environment variable (ability ``apps:env``). A variable that is not there is a 404 (``is_not_found``)."""
        check_env_key(key)
        _, data = self._request("DELETE", _app_path(slug, "env", key))

        return EnvChange.from_dict(_as_dict(data))

    def wait_for_deployment(
        self,
        slug: str,
        number: int,
        poll: float = 3.0,
        on_update: Optional[Callable[[Deployment], None]] = None,
        timeout: Optional[float] = None,
    ) -> Deployment:
        """Poll a deployment until it is finished and return the final state.

        Args:
            poll: Seconds between looks (default 3, at least 1).
            on_update: Called with every look.
            timeout: Give up after this many seconds (raises ``WaitTimeoutError``; the deployment carries on in the panel).

        Check ``succeeded`` (and ``status``) on the result: a deployment can finish as failed or rolled back.
        """
        if not isinstance(poll, (int, float)) or poll < 1:
            poll = 3.0

        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            deployment = self.get_deployment(slug, number)

            if on_update is not None:
                on_update(deployment)

            if deployment.finished:
                return deployment

            wait = float(poll)

            if deadline is not None:
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    raise WaitTimeoutError("commypanel: still waiting for deployment #%d" % number)

                wait = min(wait, remaining)

            self._sleep(wait)

    # -- plumbing -------------------------------------------------------------------------

    def _control(self, slug: str, action: str) -> App:
        _, data = self._request("POST", _app_path(slug, action))

        return App.from_dict(_as_dict(data))

    def _request(
        self,
        method: str,
        path: str,
        query: Optional[Dict[str, str]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Any]:
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        target = _BASE_PATH + path

        if query:
            target += "?" + urllib.parse.urlencode(query)

        attempt = 0

        while True:
            try:
                return self._once(method, target, payload)
            except ApiError as err:
                if attempt >= self._retries or not _retryable(method, err.status):
                    raise

                wait = float(err.retry_after_seconds) if err.retry_after_seconds > 0 else 0.5 * (2**attempt)
                self._sleep(min(wait, _MAX_RETRY_WAIT))
                attempt += 1

    def _once(self, method: str, target: str, payload: Optional[bytes]) -> Tuple[int, Any]:
        headers = {
            "Authorization": "Bearer " + self._token,
            "Accept": "application/json",
            "User-Agent": self._agent,
            "Connection": "close",
        }

        if payload is not None:
            headers["Content-Type"] = "application/json"

        # One connection per call: nothing is shared between calls or threads.
        if self._scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                self._host, self._port, timeout=self._timeout, context=self._ssl
            )
        else:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)

        try:
            try:
                conn.request(method, target, body=payload, headers=headers)
                resp = conn.getresponse()
                status = resp.status
                retry_after = _retry_after(resp.getheader("Retry-After"))

                if 300 <= status < 400:
                    raise RedirectError(
                        "commypanel: the panel answered with a redirect, which is not followed "
                        "(check the address, https and www)"
                    )

                limit = min(self._max_body, _MAX_ERROR_BODY) if status >= 400 else self._max_body
                raw = resp.read(limit + 1)
            except CommyPanelError:
                raise
            except (OSError, http.client.HTTPException) as err:
                # The address has no secret in it, but keep the token out of anything quoted.
                message = _scrub(_describe(err), self._token)
                raise TransportError("commypanel: %s %s: %s" % (method, target.split("?")[0], message)) from None
        finally:
            conn.close()

        if len(raw) > limit:
            raise ResponseTooLargeError("commypanel: the answer is too large")

        if status >= 400:
            raise _api_error(status, raw, retry_after, self._token)

        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            envelope = None

        if not isinstance(envelope, dict) or "data" not in envelope:
            raise CommyPanelError(
                "commypanel: the answer is not the JSON the API gives (is %s a CommyPanel?)" % self.base_url
            )

        return status, envelope["data"]


# -- helpers ---------------------------------------------------------------------------------


def _check_base_url(raw: str, allow_http_loopback: bool) -> Tuple[str, str, str, int]:
    if not isinstance(raw, str):
        raise InvalidURLError("commypanel: the panel address must look like https://panel.example.com")

    invalid = InvalidURLError("commypanel: the panel address must look like https://panel.example.com")

    try:
        parts = urllib.parse.urlsplit(raw.strip())
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise invalid from None

    if not parts.netloc or not host:
        raise invalid

    if "@" in parts.netloc or parts.query or parts.fragment or "?" in raw or "#" in raw:
        raise invalid

    if parts.path not in ("", "/") and parts.path.rstrip("/") != _BASE_PATH:
        raise invalid

    if parts.scheme == "https":
        pass
    elif parts.scheme == "http":
        if not allow_http_loopback or not _is_loopback(host):
            raise InsecureURLError("commypanel: the panel address must be https")
    else:
        raise InsecureURLError("commypanel: the panel address must be https")

    return parts.scheme, parts.netloc, host, port if port is not None else (443 if parts.scheme == "https" else 80)


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True

    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_token(token: object) -> None:
    if not isinstance(token, str) or token == "" or len(token) > 512:
        raise InvalidTokenError("commypanel: the token is empty or has characters a token cannot have")

    for ch in token:
        if ch <= " " or ch == "\x7f":
            raise InvalidTokenError("commypanel: the token is empty or has characters a token cannot have")


def _tls_context(ca_cert_pem: Optional[str]) -> ssl.SSLContext:
    context = ssl.create_default_context()  # verifies the certificate and the host name
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    if ca_cert_pem:
        pem = ca_cert_pem.decode("ascii", "replace") if isinstance(ca_cert_pem, bytes) else ca_cert_pem

        try:
            context.load_verify_locations(cadata=pem)
        except ssl.SSLError:
            raise ValueError("commypanel: the CA certificate is not valid PEM") from None

        if "BEGIN CERTIFICATE" not in pem:
            raise ValueError("commypanel: the CA certificate is not valid PEM")

    return context


def _app_path(slug: str, *rest: str) -> str:
    path = "/apps/" + check_slug(slug)

    for part in rest:
        path += "/" + part

    return path


def _retryable(method: str, status: int) -> bool:
    # A 429 means the panel did not do the work, so any call may be repeated; a gateway error is only
    # repeated for calls that read (a write may have happened).
    if status == 429:
        return True

    if status in (502, 503, 504):
        return method == "GET"

    return False


def _retry_after(value: Optional[str]) -> int:
    try:
        seconds = int((value or "").strip())
    except ValueError:
        return 0

    return seconds if seconds > 0 else 0


def _api_error(status: int, raw: bytes, retry_after: int, token: str) -> ApiError:
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None

    # A misbehaving server could echo the Authorization header into its error text, and that text ends up in
    # the caller's logs: nothing the panel says is allowed to carry the token.
    body = _redact(body, token)

    if isinstance(body, dict):
        error = body.get("error")
        message = body.get("message")
        text = error if isinstance(error, str) and error else (message if isinstance(message, str) and message else "")

        if text:
            fields: Dict[str, List[str]] = {}
            raw_fields = body.get("errors")

            if isinstance(raw_fields, dict):
                for name, problems in raw_fields.items():
                    if isinstance(problems, list):
                        fields[str(name)] = [str(p) for p in problems]

            deployment = body.get("deployment")

            return ApiError(
                status,
                text,
                fields,
                Deployment.from_dict(deployment) if isinstance(deployment, dict) else None,
                retry_after,
            )

    # A proxy or a crash answered with something that is not the API's JSON: say what it was, not what it said.
    try:
        phrase = http.HTTPStatus(status).phrase
    except ValueError:
        phrase = "Error"

    return ApiError(status, phrase + " (not an answer from the CommyPanel API)", None, None, retry_after)


def _describe(err: BaseException) -> str:
    if isinstance(err, (socket.timeout, TimeoutError)):
        return "timed out"

    if isinstance(err, ssl.SSLError):
        return str(err)  # "certificate verify failed: IP address mismatch ..." says why

    reason = getattr(err, "reason", None)

    return str(reason or err) or err.__class__.__name__


def _redact(value: Any, token: str) -> Any:
    """Replaces the token with "[redacted]" in every string of a decoded JSON value (keys too)."""
    if isinstance(value, str):
        return _scrub(value, token)

    if isinstance(value, list):
        return [_redact(item, token) for item in value]

    if isinstance(value, dict):
        return {_scrub(str(key), token): _redact(item, token) for key, item in value.items()}

    return value


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "[redacted]") if token and token in text else text


def _as_dict(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise CommyPanelError("commypanel: reading the answer: an object was expected")

    return data


def _as_list(data: Any) -> List[Any]:
    if not isinstance(data, list):
        raise CommyPanelError("commypanel: reading the answer: a list was expected")

    return data
