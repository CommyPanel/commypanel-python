"""Names are checked before any request, so an app or variable name cannot change the path."""

from __future__ import annotations

import re

from ._errors import InvalidInputError

# fullmatch, not match with $: "$" would let a trailing newline through.
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")


def check_slug(slug: object) -> str:
    if not isinstance(slug, str) or _SLUG.fullmatch(slug) is None:
        raise InvalidInputError("commypanel: invalid app or variable name")

    return slug


def check_env_key(key: object) -> str:
    if not isinstance(key, str) or _ENV_KEY.fullmatch(key) is None:
        raise InvalidInputError("commypanel: invalid app or variable name")

    return key


def check_number(number: object) -> int:
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise InvalidInputError("commypanel: invalid app or variable name")

    return number
