# commypanel-python

A small Python client for the HTTP API of a [CommyPanel](https://github.com/CommyPanel/panel) server: list
apps, start and follow deployments, start, stop and restart an app, read its logs and manage its
environment variables.

- **No dependencies.** Python standard library only, Python 3.9 or newer. Fully typed (`py.typed`).
- **Hard to misuse.** https only, no redirects, bounded retries and answers, and the token kept out of
  errors and `repr`. See [Security](#security).
- **Matches the API.** `testdata/openapi.yaml` is a copy of the panel's API description, and a test fails
  when the API gains a call this library does not have.

```bash
pip install commypanel
```

(Until the first release is on PyPI, install from a checkout: `pip install .`.)

## Use

Create a token in the panel under **Settings > API tokens**. Give it only what it needs (for a deploy job:
`apps:deploy` and `apps:read`), limit it to one app, and let it expire.

```python
import os
from commypanel import Client, is_conflict

client = Client("https://panel.example.com", os.environ["COMMY_TOKEN"])

try:
    deployment = client.start_deployment("shop")
except Exception as err:
    if is_conflict(err):          # one is already running: err.deployment is that one
        raise SystemExit("a deployment is already running: #%d" % err.deployment.number)
    raise

deployment = client.wait_for_deployment(
    "shop", deployment.number, poll=3, on_update=lambda d: print(d.status), timeout=600
)

if not deployment.succeeded:
    raise SystemExit("the deployment ended as %s: %s" % (deployment.status, deployment.error))
```

Errors from the panel are `commypanel.ApiError` (with `status`, `message`, `fields`, `deployment` and
`retry_after_seconds`); test them with `is_not_found`, `is_forbidden`, `is_conflict`, `is_unauthorized` and
`is_rate_limited`. Everything this library raises on purpose derives from `commypanel.CommyPanelError`.

| Method | API call | Ability |
|---|---|---|
| `token()` | `GET /token` | none |
| `list_apps()`, `get_app(slug)` | `GET /apps`, `GET /apps/{slug}` | `apps:read` |
| `list_deployments(slug, limit=None)`, `get_deployment(slug, number, with_log=False)` | `GET /apps/{slug}/deployments[/{n}]` | `apps:read` |
| `start_deployment(slug)`, `apply_changes(slug)` | `POST /apps/{slug}/deployments`, `/apply` | `apps:deploy` |
| `start_app(slug)`, `stop_app(slug)`, `restart_app(slug)` | `POST /apps/{slug}/start`, `/stop`, `/restart` | `apps:control` |
| `logs(slug, tail=None)` | `GET /apps/{slug}/logs` | `apps:logs` |
| `list_env(slug)`, `set_env(slug, key, value)`, `unset_env(slug, key)` | `GET`, `PUT`, `DELETE /apps/{slug}/env[/{key}]` | `apps:env` |
| `wait_for_deployment(slug, number, poll=3, on_update=None, timeout=None)` | polls `GET .../deployments/{n}` | `apps:read` |

Environment variable **values are write-only**: the API never returns them, so `list_env` gives names, and
`set_env` returns `(change, created)`.

## Security

- **https only.** `Client` refuses any other address. `allow_http_loopback=True` allows plain http for
  `localhost`, `127.0.0.1` and `::1` only, for development.
- **TLS is always verified**, including the host name. There is no option to skip it. For a panel with a
  private CA pass `ca_cert_pem=` (a PEM string).
- **Redirects are never followed**, so the token cannot be handed to another address; a redirect raises
  `RedirectError`.
- **The token stays out of sight.** It is only ever in the `Authorization` header: not in URLs, error
  messages, `repr()`, `str()` or formatting, and a `Client` cannot be pickled.
- **Bounded.** A timeout (30 s per network operation), at most 2 retries (never for a write that may have
  happened: only a 429, and gateway errors for reads), `Retry-After` capped at 30 s, answers capped at
  16 MiB.
- **Names are checked before any request**, so an app or variable name cannot change the path.
- **No dependencies and no install-time code**: nothing runs when you install it.

Report a security problem privately, as described in [SECURITY.md](SECURITY.md).

## Compatibility

This library speaks API `v1` (`/api/v1`) of CommyPanel 0.10 and later. It needs Python 3.9 or newer. A
`Client` keeps no state between calls, so one can be shared between threads.

## Development

```bash
scripts/sync-spec.sh ../../commypanel                  # copy the API description from the panel repository
python3 -m unittest discover -s tests -v               # no test dependencies
```

`tests/fixtures/tls` holds throwaway test-only certificates (see the README there).

## Publishing

Not yet published to PyPI. When it is, it will be from CI with PyPI trusted publishing (no long-lived
token) and signed attestations, set up as a deliberate step of its own.

MIT licensed.
