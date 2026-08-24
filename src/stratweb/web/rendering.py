"""One hardened Jinja environment for every server-rendered page."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from jinja2 import Environment, PackageLoader, pass_context, select_autoescape
from jinja2.runtime import Context
from markupsafe import Markup

from stratweb.web.i18n import (
    DEFAULT_LOCALE,
    UI_LOCALE_SCHEMA_VERSION,
    buy_type_label,
    map_display_name,
    status_label,
    team_display_name,
    translate,
    warning_label,
)

_STATIC_ROOT = Path(__file__).with_name("static")
DESIGN_SYSTEM_VERSION = "2.0.0"


def static_asset(relative_path: str) -> str:
    """Return a cache-busted URL for one packaged static asset."""

    normalized = PurePosixPath(relative_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("Static asset paths must stay inside the packaged static directory")
    source = _STATIC_ROOT.joinpath(*normalized.parts)
    stat = source.stat()
    version = f"{stat.st_mtime_ns:x}-{stat.st_size:x}"
    return f"/static/{normalized.as_posix()}?v={version}"


@lru_cache(maxsize=1)
def environment() -> Environment:
    result = Environment(
        loader=PackageLoader("stratweb.web", "templates"),
        autoescape=select_autoescape(("html", "xml")),
        enable_async=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    result.globals["static_asset"] = static_asset
    result.globals["design_system_version"] = DESIGN_SYSTEM_VERSION
    result.globals["t"] = _translate_for_context
    result.globals["ui_locale_schema_version"] = UI_LOCALE_SCHEMA_VERSION
    result.filters["status_label"] = _status_for_context
    result.filters["team_name"] = _team_for_context
    result.filters["map_name"] = map_display_name
    result.filters["buy_type"] = _buy_type_for_context
    result.filters["warning_label"] = _warning_for_context
    return result


@pass_context
def _translate_for_context(context: Context, key: str, **values: object) -> str:
    return translate(key, locale=str(context.get("ui_locale", DEFAULT_LOCALE)), **values)


@pass_context
def _status_for_context(context: Context, value: object) -> str:
    return status_label(value, locale=str(context.get("ui_locale", DEFAULT_LOCALE)))


@pass_context
def _team_for_context(context: Context, value: str | None) -> str:
    return team_display_name(value, locale=str(context.get("ui_locale", DEFAULT_LOCALE)))


@pass_context
def _buy_type_for_context(context: Context, value: object) -> str:
    return buy_type_label(value, locale=str(context.get("ui_locale", DEFAULT_LOCALE)))


@pass_context
def _warning_for_context(context: Context, value: object) -> str:
    return warning_label(value, locale=str(context.get("ui_locale", DEFAULT_LOCALE)))


def render_template(name: str, **context: Any) -> str:
    locale = str(context.pop("locale", DEFAULT_LOCALE))
    return environment().get_template(name).render(ui_locale=locale, **context)


def render_legacy_content(title: str, content: str, **context: Any) -> str:
    """Temporary compatibility bridge while preserving autoescape at route boundaries."""

    return render_template(
        "legacy_content.html",
        title=title,
        content=Markup(content),
        **context,
    )
