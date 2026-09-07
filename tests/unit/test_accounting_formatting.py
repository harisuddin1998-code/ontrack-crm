"""
Accounting number formatting.

Every amount in the CRM must read as money: thousands separated, exactly two
decimal places. A column of figures that mixes `9000`, `9000.0` and
`9,000.00` cannot be scanned, and the two-decimal rule is what makes it
scannable.
"""
import pytest

from src.utils.formatting import format_amount, format_count, format_money


@pytest.mark.parametrize('value,expected', [
    (9000, '9,000.00'),
    (9000.0, '9,000.00'),
    ('9000', '9,000.00'),
    (1234567.891, '1,234,567.89'),
    (0, '0.00'),
    (0.5, '0.50'),
    (-2500, '-2,500.00'),
    (999.999, '1,000.00'),
])
def test_amounts_always_carry_separators_and_two_decimals(value, expected):
    assert format_amount(value) == expected


def test_a_round_number_keeps_its_trailing_zeros():
    """9000 must not render as `9,000.0` or `9000`."""
    rendered = format_amount(9000)
    assert rendered.endswith('.00')
    assert ',' in rendered


def test_missing_values_are_a_dash_not_a_zero():
    """No value recorded and zero are different facts."""
    assert format_amount(None) == '-'
    assert format_amount('') == '-'
    assert format_amount(0) == '0.00'


def test_missing_values_can_be_forced_to_zero_where_a_total_needs_one():
    assert format_amount(None, dash_if_empty=False) == '0.00'


def test_unparseable_input_does_not_raise():
    """Templates hand this whatever they hold; it must never break a page."""
    assert format_amount('not a number') == '-'
    assert format_amount(object()) == '-'


def test_money_adds_the_currency_prefix():
    assert format_money(9000) == 'PKR 9,000.00'
    assert format_money(None) == '-'


def test_already_formatted_strings_round_trip():
    """Re-formatting an amount that already has commas must not corrupt it."""
    assert format_amount('1,234.50') == '1,234.50'


def test_counts_get_separators_but_no_decimals():
    """A count of vehicles is not money."""
    assert format_count(1500) == '1,500'
    assert format_count(0) == '0'
    assert format_count(None) == '0'
    assert format_count(12.7) == '12'


def test_filters_are_registered_on_the_app():
    from src.app import create_app

    app = create_app('testing')
    for filter_name in ('money', 'money_pkr', 'amount', 'count_fmt'):
        assert filter_name in app.jinja_env.filters

    with app.app_context():
        rendered = app.jinja_env.from_string('{{ v|money_pkr }}').render(v=9000)
        assert rendered == 'PKR 9,000.00'
