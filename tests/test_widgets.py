import pytest

# customtkinter is not installed in the test environment; the rest of the package stays importable.
ctk = pytest.importorskip("customtkinter")

from commendbot_panel.ui.widgets import format_clock  # noqa: E402


# A11 — the original wrote "if 9 > dt.minute" and rendered minute 9 as "14:9".
def test_format_clock_pads_minute_nine_to_two_digits():
    assert format_clock(14, 9) == "14:09"


def test_format_clock_pads_the_hour_too():
    assert format_clock(9, 5) == "09:05"


def test_format_clock_leaves_two_digit_values_alone():
    assert format_clock(14, 30) == "14:30"
