from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from stratweb.main import create_app
from stratweb.web.i18n import (
    SUPPORTED_LOCALES,
    UI_LOCALE_SCHEMA_VERSION,
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
    assert f'data-locale-schema-version="{UI_LOCALE_SCHEMA_VERSION}"' in response.text
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


def test_tactical_mobile_and_submit_feedback_contract(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "tactical-mobile.duckdb")) as client:
        tactical_css = client.get("/static/css/tactical-v2.css")
        feedback_js = client.get("/static/js/form-feedback.js")

    assert tactical_css.status_code == 200
    assert "@media (max-width: 700px)" in tactical_css.text
    assert "@media (max-width: 460px)" in tactical_css.text
    assert ".evidence-actions { grid-template-columns: 1fr; }" in tactical_css.text
    assert ".tactical-coach-banner" in tactical_css.text
    assert ".evidence-plain-summary" in tactical_css.text
    assert ".analyst-note-form textarea" in tactical_css.text
    assert feedback_js.status_code == 200
    assert "form[data-submit-feedback]" in feedback_js.text
    assert 'form.setAttribute("aria-busy", "true")' in feedback_js.text
    assert "button.disabled = true" in feedback_js.text
    assert 'window.addEventListener("pageshow"' in feedback_js.text


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
