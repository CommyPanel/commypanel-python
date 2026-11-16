"""The objects the API returns. They never hold secrets, and environment variable values are not among them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


class Ability:
    """What a token may do (the strings the API uses)."""

    READ = "apps:read"
    DEPLOY = "apps:deploy"
    CONTROL = "apps:control"
    LOGS = "apps:logs"
    ENV = "apps:env"


class DeployStrategy:
    """How a new release replaces the running one."""

    #: The new version starts beside the old one (no downtime).
    ROLLING = "rolling"
    #: The old version stops first, for software that cannot run twice on the same data.
    STOP_FIRST = "stop_first"


def _time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None

    text = value[:-1] + "+00:00" if value.endswith("Z") else value

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _opt_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class Token:
    """The token the client is using."""

    name: str
    abilities: List[str]
    #: The apps the token is limited to; None means every app its owner may use.
    apps: Optional[List[str]]
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    #: The owner's name.
    owner: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Token":
        apps = d.get("apps")

        return cls(
            name=str(d.get("name", "")),
            abilities=[str(a) for a in d.get("abilities") or []],
            apps=None if apps is None else [str(a) for a in apps],
            expires_at=_time(d.get("expires_at")),
            last_used_at=_time(d.get("last_used_at")),
            owner=str(d.get("owner", "")),
        )


@dataclass(frozen=True)
class Deployment:
    """One deployment, rollback or "apply changes"."""

    number: int
    status: str
    stage: Optional[str]
    #: True once it is over, whatever the result. Poll until it is.
    finished: bool
    #: Only meaningful once finished. A watched release can still be rolled back later (status "rolled_back").
    succeeded: bool
    commit: Optional[str]
    commit_message: Optional[str]
    strategy: str
    is_rollback: bool
    error: Optional[str]
    created_at: Optional[datetime]
    finished_at: Optional[datetime]
    url: str
    #: The build log, only when asked for.
    log: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Deployment":
        return cls(
            number=int(d.get("number", 0)),
            status=str(d.get("status", "")),
            stage=_opt_str(d.get("stage")),
            finished=bool(d.get("finished", False)),
            succeeded=bool(d.get("succeeded", False)),
            commit=_opt_str(d.get("commit")),
            commit_message=_opt_str(d.get("commit_message")),
            strategy=str(d.get("strategy", "")),
            is_rollback=bool(d.get("is_rollback", False)),
            error=_opt_str(d.get("error")),
            created_at=_time(d.get("created_at")),
            finished_at=_time(d.get("finished_at")),
            url=str(d.get("url", "")),
            log=str(d.get("log", "") or ""),
        )


@dataclass(frozen=True)
class App:
    """One app. It never holds secrets."""

    slug: str
    name: str
    status: str
    stack: Optional[str]
    deploy_strategy: str
    domains: List[str]
    live_deployment: Optional[int]
    latest_deployment: Optional[Deployment]
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "App":
        live = d.get("live_deployment")
        latest = d.get("latest_deployment")

        return cls(
            slug=str(d.get("slug", "")),
            name=str(d.get("name", "")),
            status=str(d.get("status", "")),
            stack=_opt_str(d.get("stack")),
            deploy_strategy=str(d.get("deploy_strategy", "")),
            domains=[str(x) for x in d.get("domains") or []],
            live_deployment=int(live) if isinstance(live, int) else None,
            latest_deployment=Deployment.from_dict(latest) if isinstance(latest, dict) else None,
            created_at=_time(d.get("created_at")),
        )


@dataclass(frozen=True)
class Logs:
    """The output of an app's running container."""

    #: False when the app has no running container.
    live: bool
    lines: int
    logs: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Logs":
        return cls(live=bool(d.get("live", False)), lines=int(d.get("lines", 0)), logs=str(d.get("logs", "") or ""))


@dataclass(frozen=True)
class EnvKeys:
    """The names of an app's environment variables. Values are never returned by the API."""

    keys: List[str] = field(default_factory=list)
    #: True when variables, volumes or links changed after the running container was made: call apply_changes.
    pending_changes: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EnvKeys":
        return cls(keys=[str(k) for k in d.get("keys") or []], pending_changes=bool(d.get("pending_changes", False)))


@dataclass(frozen=True)
class EnvChange:
    """The answer to setting or removing a variable. The value is not part of it."""

    key: str
    pending_changes: bool

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EnvChange":
        return cls(key=str(d.get("key", "")), pending_changes=bool(d.get("pending_changes", False)))
