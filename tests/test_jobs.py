import pytest

from commendbot_panel.constants import MAX_CONCURRENT_JOBS, RESELLER_ONLY_JOBS
from commendbot_panel.jobs import (
    Balance,
    BulkEntry,
    Order,
    Rejection,
    Slot,
    describe,
    parse_bulk_file,
    parse_bulk_line,
    parse_slot_label,
    validate_order,
)

STEAM_ID = 76561198012345678
RICH = Balance(amount=1000)


def slot(**overrides):
    defaults = dict(id=3, name="Fast", enabled=True, currency=1000)
    return Slot(**{**defaults, **overrides})


def order(amount=10, **slot_overrides):
    return Order(steam_id64=STEAM_ID, amount=amount, slot=slot(**slot_overrides))


def test_slot_label_is_id_dot_name():
    assert slot().label == "3.Fast"


def test_a_plain_order_is_accepted():
    assert validate_order(order(), RICH, active_jobs=0).accepted is True


def test_an_accepted_decision_describes_as_empty_text():
    assert describe(validate_order(order(), RICH, active_jobs=0)) == ""


def test_a_disabled_slot_is_refused():
    assert validate_order(order(enabled=False), RICH, active_jobs=0).rejection is Rejection.SLOT_DISABLED


# A5 — the old message named min_commends while the check compared against 0.
def test_validate_order_rejects_an_amount_below_slot_min_commends():
    decision = validate_order(order(amount=3, min_commends=5), RICH, active_jobs=0)
    assert decision.rejection is Rejection.BELOW_MINIMUM
    assert decision.detail == "minimum is 5"


def test_validate_order_accepts_exactly_the_slot_minimum():
    assert validate_order(order(amount=5, min_commends=5), RICH, active_jobs=0).accepted


def test_zero_commends_is_below_the_minimum_even_when_the_slot_sets_none():
    assert validate_order(order(amount=0), RICH, active_jobs=0).rejection is Rejection.BELOW_MINIMUM


def test_an_amount_above_the_slot_maximum_is_refused():
    decision = validate_order(order(amount=101, max_commends=100), RICH, active_jobs=0)
    assert decision.rejection is Rejection.ABOVE_MAXIMUM


def test_a_zero_maximum_means_unlimited():
    assert validate_order(order(amount=900, max_commends=0), RICH, active_jobs=0).accepted


def test_an_order_larger_than_the_slot_currency_is_refused():
    assert validate_order(order(amount=50, currency=10), RICH, active_jobs=0).rejection is Rejection.SLOT_EXHAUSTED


def test_the_daily_cap_counts_what_was_already_used_today():
    decision = validate_order(order(amount=10, max_daily_commends=25), Balance(1000, today_used=20), active_jobs=0)
    assert decision.rejection is Rejection.DAILY_LIMIT
    assert decision.detail == "5 of 25 left today"


def test_a_zero_daily_cap_means_unlimited():
    assert validate_order(order(amount=10, max_daily_commends=0), Balance(1000, today_used=999), active_jobs=0).accepted


def test_an_order_larger_than_the_balance_is_refused():
    decision = validate_order(order(amount=10), Balance(amount=4), active_jobs=0)
    assert decision.rejection is Rejection.INSUFFICIENT_BALANCE
    assert decision.detail == "4 commends left"


def test_a_blacklisted_target_is_refused():
    decision = validate_order(order(), RICH, active_jobs=0, target_blacklisted=True)
    assert decision.rejection is Rejection.TARGET_BLACKLISTED


def test_a_target_that_is_already_running_is_refused():
    decision = validate_order(order(), RICH, active_jobs=0, target_already_running=True)
    assert decision.rejection is Rejection.ALREADY_RUNNING


# A6 — "tdb >= 5 or tdb >= 5 and userid != x" collapsed to one limit for everybody.
def test_a_reseller_may_exceed_the_reseller_only_threshold():
    decision = validate_order(order(), RICH, active_jobs=RESELLER_ONLY_JOBS, is_reseller=True)
    assert decision.accepted is True


# A6 — but the hard concurrency limit applies to resellers too.
def test_nobody_may_exceed_the_hard_concurrency_limit():
    for reseller in (False, True):
        decision = validate_order(order(), RICH, active_jobs=MAX_CONCURRENT_JOBS, is_reseller=reseller)
        assert decision.rejection is Rejection.TOO_MANY_JOBS


def test_a_non_reseller_is_refused_at_the_reseller_only_threshold():
    decision = validate_order(order(), RICH, active_jobs=RESELLER_ONLY_JOBS, is_reseller=False)
    assert decision.rejection is Rejection.RESELLER_ONLY


def test_a_non_reseller_may_run_up_to_the_reseller_only_threshold():
    assert validate_order(order(), RICH, active_jobs=RESELLER_ONLY_JOBS - 1).accepted


def test_the_cheapest_rule_wins_when_several_would_fail():
    decision = validate_order(order(amount=0, enabled=False), Balance(0), active_jobs=99)
    assert decision.rejection is Rejection.SLOT_DISABLED


def test_describe_appends_the_detail_in_brackets():
    decision = validate_order(order(amount=3, min_commends=5), RICH, active_jobs=0)
    assert describe(decision) == "That is fewer commends than the slot allows. (minimum is 5)"


def test_describe_omits_the_brackets_when_there_is_no_detail():
    decision = validate_order(order(enabled=False), RICH, active_jobs=0)
    assert describe(decision) == "This slot is disabled."


def test_parse_slot_label_takes_the_number_before_the_dot():
    assert parse_slot_label("3.Fast") == 3


def test_parse_slot_label_rejects_a_label_without_a_leading_number():
    with pytest.raises(ValueError):
        parse_slot_label("Fast")


def test_parse_bulk_line_reads_three_fields():
    assert parse_bulk_line("bot_one:pw123:40") == BulkEntry("bot_one", "pw123", 40, None)


def test_parse_bulk_line_reads_the_optional_shared_secret():
    assert parse_bulk_line("bot_one:pw123:40:SECRET==").shared_secret == "SECRET=="


def test_parse_bulk_line_rejects_a_non_numeric_amount():
    with pytest.raises(ValueError, match="not a number"):
        parse_bulk_line("bot_one:pw123:many")


def test_parse_bulk_line_rejects_a_wrong_field_count():
    with pytest.raises(ValueError, match="expected login"):
        parse_bulk_line("bot_one:pw123")


def test_parse_bulk_line_rejects_an_empty_login():
    with pytest.raises(ValueError, match="must not be empty"):
        parse_bulk_line("  :pw123:40")


def test_parse_bulk_file_skips_blank_lines_and_comments():
    text = "# accounts\n\nbot_one:pw1:10\n\nbot_two:pw2:20\n"
    assert [entry.login for entry in parse_bulk_file(text)] == ["bot_one", "bot_two"]


def test_parse_bulk_file_reports_the_offending_line_number():
    text = "bot_one:pw1:10\n\nbot_two:pw2:lots\n"
    with pytest.raises(ValueError, match="^line 3: "):
        parse_bulk_file(text)


def test_parse_bulk_file_returns_an_empty_list_for_an_empty_file():
    assert parse_bulk_file("\n# only a comment\n") == []
