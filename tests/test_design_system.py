from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from stratweb.main import create_app
from stratweb.web.i18n import (
    SUPPORTED_LOCALES,
    map_display_name,
    resolve_locale,
    team_display_name,
    translate,
    warning_label,
)
from stratweb.web.locale_catalogs import CATALOGS
from stratweb.web.rendering import DESIGN_SYSTEM_VERSION


def test_style_guide_exposes_versioned_design_system(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "style-guide.duckdb")) as client:
        response = client.get("/ui/style-guide")
        tokens = client.get("/static/css/tokens.css")

    assert response.status_code == 200
    assert f'data-design-system-version="{DESIGN_SYSTEM_VERSION}"' in response.text
    assert "StratWeb design system" in response.text
    assert "Primary action" in response.text
    assert "Available" in response.text
    assert tokens.status_code == 200
    assert f'--design-system-version: "{DESIGN_SYSTEM_VERSION}"' in tokens.text
    assert "--color-surface-1" in tokens.text


def test_regular_ui_page_inherits_design_system_contract(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "library.duckdb")) as client:
        response = client.get("/ui")

    assert response.status_code == 200
    assert f'data-design-system-version="{DESIGN_SYSTEM_VERSION}"' in response.text
    assert "/static/css/tokens.css?v=" in response.text
    assert "/static/css/layout.css?v=" in response.text
    assert "/static/css/components.css?v=" in response.text
    assert "/static/css/polish.css?v=" in response.text
    assert "/static/js/shell-nav.js?v=" in response.text
    assert 'data-nav-exact="/ui"' in response.text


def test_polish_layer_hardens_narrow_screens_and_reduced_motion(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "polish.duckdb")) as client:
        response = client.get("/static/css/polish.css")

    assert response.status_code == 200
    assert "@media (max-width: 700px)" in response.text
    assert "@media (prefers-reduced-motion: reduce)" in response.text
    assert "overflow-wrap: anywhere" in response.text


def test_russian_presentation_hides_technical_placeholders() -> None:
    assert team_display_name("TeamAlpha") == "Команда 1"
    assert team_display_name("TeamBravo · CT") == "Команда 2 · CT"
    assert map_display_name("de_dust2") == "Dust II"
    assert warning_label("Match is ready") == "Матч готов"
    assert warning_label("10 player summaries") == "Игроков в статистике: 10"
    assert warning_label("9037 authoritative samples") == "Подтверждённых снимков: 9037"


def test_locale_contract_is_explicit_and_does_not_guess_unknown_languages() -> None:
    assert SUPPORTED_LOCALES == ("ru", "en")
    assert resolve_locale("en", "ru") == "en"
    assert resolve_locale(None, "en-US") == "en"
    assert resolve_locale("de", "en") == "en"
    assert resolve_locale("de", "fr") == "ru"
    assert translate("tactical.page_title", locale="en") == "Tactical overview"
    assert translate("missing.stable.key", locale="en") == "missing.stable.key"
    assert team_display_name("TeamAlpha", locale="en") == "Team 1"
    assert warning_label("small_corpus:2/20_matches", locale="en") == (
        "Small sample: 2 of 20 recommended matches"
    )
    assert CATALOGS["ru"].keys() == CATALOGS["en"].keys()
    assert not any(
        any("а" <= character.casefold() <= "я" or character.casefold() == "ё" for character in text)
        for key, text in CATALOGS["en"].items()
        if not key.startswith("locale.")
    )
