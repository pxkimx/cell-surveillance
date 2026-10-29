"""Both looks keep text readable, and the app opens in each."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cellsurveillance import history, theme  # noqa: E402


@pytest.mark.parametrize("name", theme.THEMES)
def test_text_contrast_is_at_least_4_5_to_1(name):
    p = theme.PALETTES[name]
    for fg in ("ink", "ink2", "muted", "accent"):
        for bg in ("bg", "panel"):
            assert theme.contrast(p[fg], p[bg]) >= 4.5, (name, fg, bg)


def test_dark_is_the_default_and_bad_values_fall_back(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "PREFERENCES", str(tmp_path / "preferences.json"))
    assert theme.current() == "dark"
    history.set_preference("theme", "light")
    assert theme.current() == "light"
    history.set_preference("theme", "purple")
    assert theme.current() == "dark"


def test_streamlit_flags_follow_the_look():
    assert "light" in theme.streamlit_flags("light") and "dark" in theme.streamlit_flags("dark")
    assert "--theme.backgroundColor" in theme.streamlit_flags("light")


def test_css_variables_are_complete():
    for name in theme.THEMES:
        css = theme.css_variables(name)
        for var in ("--bg", "--ink", "--veil", "--nav-active-ink", "--media-bg"):
            assert var + ":" in css
        assert f"color-scheme: {name}" in css
