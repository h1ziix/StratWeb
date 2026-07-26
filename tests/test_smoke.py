"""Minimal package smoke test for the stage-1 foundation."""


def test_application_imports() -> None:
    from stratweb.main import app

    assert app.title == "StratWeb"
