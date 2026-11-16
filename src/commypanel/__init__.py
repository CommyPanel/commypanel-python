"""A small client for the HTTP API of a CommyPanel server.

List apps, start and follow deployments, start, stop and restart an app, read its logs and manage its
environment variables. Standard library only, and built to be hard to misuse:

* the panel address must be https (plain http only for localhost, and only when asked for);
* redirects are never followed, so the token cannot be sent to another host;
* the token is kept out of errors, ``repr`` and formatting;
* calls have a timeout, bounded retries and a limit on the size of an answer;
* environment variable values can only be written, because the API never returns them.

Create a token in the panel under Settings > API tokens, give it only the abilities it needs, limit it to one
app and let it expire::

    import os
    from commypanel import Client

    client = Client("https://panel.example.com", os.environ["COMMY_TOKEN"])
    deployment = client.start_deployment("shop")
    deployment = client.wait_for_deployment("shop", deployment.number)
"""

from ._client import Client, __version__
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
    is_conflict,
    is_forbidden,
    is_not_found,
    is_rate_limited,
    is_unauthorized,
)
from ._types import (
    Ability,
    App,
    Deployment,
    DeployStrategy,
    EnvChange,
    EnvKeys,
    Logs,
    Token,
)

__all__ = [
    "Ability",
    "ApiError",
    "App",
    "Client",
    "CommyPanelError",
    "DeployStrategy",
    "Deployment",
    "EnvChange",
    "EnvKeys",
    "InsecureURLError",
    "InvalidInputError",
    "InvalidTokenError",
    "InvalidURLError",
    "Logs",
    "RedirectError",
    "ResponseTooLargeError",
    "Token",
    "TransportError",
    "WaitTimeoutError",
    "__version__",
    "is_conflict",
    "is_forbidden",
    "is_not_found",
    "is_rate_limited",
    "is_unauthorized",
]
