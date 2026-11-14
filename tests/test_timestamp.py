"""Timestamp construction contract tests.

This module covers the four timestamp construction paths in the safe
constructor (date-only, fractional seconds, UTC offset, datetime) and the
error contract they now share:

* every failure is a ``yaml.constructor.ConstructorError`` (hence a
  ``YAMLError``), never a bare ``ValueError``/``AttributeError``;
* out-of-range components raise ``TimestampOutOfRangeError`` with a
  distinguishable ``field`` (``month``, ``day``, ``hour``, ``utc_offset``,
  plus ``minute``/``second``/``year``/``format``);
* errors carry the source mark of the offending scalar, so a broken config
  can be located without bisecting sections;
* fractional seconds keep exactly the first six digits (truncation, never
  rounding) and legal values keep yielding the same objects as before.
"""

import datetime

import pytest

import yaml
from yaml.constructor import (
    TIMESTAMP_MAX_FRACTION_DIGITS,
    ConstructorError,
    TimestampFormatError,
    TimestampOutOfRangeError,
)


def loader_classes():
    classes = [yaml.SafeLoader, yaml.FullLoader]
    if hasattr(yaml, "CSafeLoader"):
        classes.append(yaml.CSafeLoader)
    return classes


@pytest.fixture(params=loader_classes(), ids=lambda cls: cls.__name__)
def Loader(request):
    return request.param


def load(source, Loader):
    return yaml.load(source, Loader=Loader)


# ---------------------------------------------------------------------------
# Legal values: parsing products must not regress
# ---------------------------------------------------------------------------

# These expectations mirror tests/legacy_tests/data/timestamp.data and
# construct-timestamp.data verbatim.
LEGAL_TIMESTAMPS = [
    ('2001-12-15T02:59:43.1Z',
     datetime.datetime(2001, 12, 15, 2, 59, 43, 100000,
                       tzinfo=datetime.timezone.utc)),
    ('2001-12-14t21:59:43.10-05:00',
     datetime.datetime(2001, 12, 14, 21, 59, 43, 100000,
                       tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))),
    ('2001-12-14 21:59:43.10 -5',
     datetime.datetime(2001, 12, 14, 21, 59, 43, 100000,
                       tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))),
    ('2001-12-15 2:59:43.10',
     datetime.datetime(2001, 12, 15, 2, 59, 43, 100000)),
    ('2002-12-14', datetime.date(2002, 12, 14)),
    ('2001-12-14 21:59:43.10 -5:30',
     datetime.datetime(2001, 12, 14, 21, 59, 43, 100000,
                       tzinfo=datetime.timezone(
                           -datetime.timedelta(hours=5, minutes=30)))),
    ('2001-12-14 21:59:43.10 +5:30',
     datetime.datetime(2001, 12, 14, 21, 59, 43, 100000,
                       tzinfo=datetime.timezone(
                           datetime.timedelta(hours=5, minutes=30)))),
    ('2001-12-14 21:59:43.00101',
     datetime.datetime(2001, 12, 14, 21, 59, 43, 1010)),
    ('2001-12-14 21:59:43+1',
     datetime.datetime(2001, 12, 14, 21, 59, 43,
                       tzinfo=datetime.timezone(datetime.timedelta(hours=1)))),
    ('2001-12-14 21:59:43-1:30',
     datetime.datetime(2001, 12, 14, 21, 59, 43,
                       tzinfo=datetime.timezone(
                           -datetime.timedelta(hours=1, minutes=30)))),
    ('2005-07-08 17:35:04.517600',
     datetime.datetime(2005, 7, 8, 17, 35, 4, 517600)),
]


@pytest.mark.parametrize('source, expected', LEGAL_TIMESTAMPS)
def test_legal_timestamp_unchanged(Loader, source, expected):
    assert load(source, Loader) == expected
    # Same type: date-only scalars stay date, timestamp scalars stay datetime.
    assert type(load(source, Loader)) is type(expected)


# ---------------------------------------------------------------------------
# Contrast pairs: each out-of-range shape sits next to a legal neighbour
# ---------------------------------------------------------------------------

# (field, legal source, out-of-range source).  The first four fields are the
# four reported out-of-range dimensions; minute/second/year are covered too.
CONTRAST_CASES = [
    ('month', '2001-12-01', '2001-13-01'),
    ('month', '2001-01-01', '2001-00-01'),
    ('month', '2001-12-01T00:00:00Z', '2001-13-01T00:00:00Z'),
    ('day', '2001-02-28', '2001-02-30'),
    ('day', '2001-04-30', '2001-04-31'),
    ('day', '2004-02-29', '2001-02-29'),
    ('day', '2001-01-01', '2001-02-00'),
    ('hour', '2001-12-14 23:59:43', '2001-12-14 24:59:43'),
    ('hour', '2001-12-14 23:59:43Z', '2001-12-14 99:59:43Z'),
    ('minute', '2001-12-14 21:59:43', '2001-12-14 21:99:43'),
    ('second', '2001-12-14 21:59:59', '2001-12-14 21:59:99'),
    ('utc_offset', '2001-12-14 21:59:43 +23:59',
     '2001-12-14 21:59:43 +24:00'),
    ('utc_offset', '2001-12-14 21:59:43 -23:59',
     '2001-12-14 21:59:43 -24:00'),
    ('utc_offset', '2001-12-14 21:59:43 +23:59',
     '2001-12-14 21:59:43 +25:00'),
    ('utc_offset', '2001-12-14 21:59:43 +5:59',
     '2001-12-14 21:59:43 +5:99'),
    ('year', '2001-12-14', '0000-12-14'),
]

FOUR_REPORTED_DIMENSIONS = {'month', 'day', 'hour', 'utc_offset'}


@pytest.mark.parametrize('field, valid_source, invalid_source', CONTRAST_CASES)
def test_valid_counterpart_loads(Loader, field, valid_source, invalid_source):
    value = load(valid_source, Loader)
    assert isinstance(value, (datetime.date, datetime.datetime))


@pytest.mark.parametrize('field, valid_source, invalid_source', CONTRAST_CASES)
def test_invalid_counterpart_is_marked_constructor_error(
        Loader, field, valid_source, invalid_source):
    with pytest.raises(ConstructorError) as excinfo:
        load(invalid_source, Loader)
    exc = excinfo.value
    assert isinstance(exc, TimestampOutOfRangeError)
    assert isinstance(exc, yaml.YAMLError)
    assert exc.field == field
    assert exc.problem_mark is not None
    # The mark points at the offending scalar itself, not just the document.
    assert exc.problem_mark.line == 0
    assert exc.problem_mark.column == 0
    assert 'timestamp' in str(exc)
    assert 'out of range' in str(exc)


def test_error_categories_are_distinguishable(Loader):
    errors = {}
    for field, valid_source, invalid_source in CONTRAST_CASES:
        with pytest.raises(TimestampOutOfRangeError) as excinfo:
            load(invalid_source, Loader)
        errors.setdefault(field, []).append(excinfo.value)
    # The four reported dimensions are all present and separable.
    assert FOUR_REPORTED_DIMENSIONS <= set(errors)
    assert set(errors) == {'year', 'month', 'day', 'hour', 'minute',
                           'second', 'utc_offset'}
    for field, excs in errors.items():
        assert {type(exc) for exc in excs} == {TimestampOutOfRangeError}
        assert all(exc.field == field for exc in excs)
        assert all(exc.problem_mark is not None for exc in excs)
        assert all('expected' in exc.problem for exc in excs)
    assert {exc.problem.split(' is out of range')[0]
            for exc in errors['month']} == {'month 13', 'month 0'}


def test_offset_messages_name_the_offset(Loader):
    with pytest.raises(TimestampOutOfRangeError) as excinfo:
        load('2001-12-14 21:59:43 +5:99', Loader)
    exc = excinfo.value
    assert exc.field == 'utc_offset'
    assert exc.value == '+5:99'
    assert "'+5:99'" in exc.problem


# ---------------------------------------------------------------------------
# Malformed scalars reachable through an explicit !!timestamp tag
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('source', ['!!timestamp foo', '!!timestamp 2001-12-14T',
                                    '!!timestamp ""',
                                    '!!timestamp 2001-12-14 21:59'])
def test_format_error_is_constructor_error(Loader, source):
    with pytest.raises(ConstructorError) as excinfo:
        load(source, Loader)
    exc = excinfo.value
    assert isinstance(exc, TimestampFormatError)
    assert isinstance(exc, yaml.YAMLError)
    assert exc.field == 'format'
    assert exc.problem_mark is not None


def test_explicit_tag_with_short_month_and_day_still_loads(Loader):
    # The timestamp grammar has always accepted single-digit month/day, so
    # rejecting them in the format path would be a regression.
    assert load('!!timestamp 2001-1-1', Loader) == datetime.date(2001, 1, 1)


# ---------------------------------------------------------------------------
# Fractional second precision: truncate to microseconds, never round
# ---------------------------------------------------------------------------

FRACTION_CASES = [
    # (fraction digits as authored, expected microsecond value)
    ('5', 500000),
    ('05', 50000),
    ('00101', 1010),
    ('123456', 123456),
    ('517600', 517600),
    ('1234567', 123456),      # 7th digit dropped
    ('1234569', 123456),      # truncated, not rounded to 123457
    ('123456789', 123456),
    ('0000001', 0),
    ('9999999', 999999),      # no carry into the second
    ('1', 100000),
]


@pytest.mark.parametrize('digits, microsecond', FRACTION_CASES)
def test_fraction_truncated_to_microseconds(Loader, digits, microsecond):
    value = load('2001-12-14 21:59:43.%s' % digits, Loader)
    assert value == datetime.datetime(2001, 12, 14, 21, 59, 43, microsecond)
    assert value.microsecond == microsecond
    # Truncation never touches the whole-second component.
    assert value.second == 43


def test_fraction_contract_constant():
    assert TIMESTAMP_MAX_FRACTION_DIGITS == 6


@pytest.mark.parametrize('digits, microsecond', FRACTION_CASES)
def test_fraction_truncation_matches_across_loader_classes(digits, microsecond):
    products = {cls: load('2001-12-14 21:59:43.%s' % digits, cls)
                for cls in loader_classes()}
    assert set(products.values()) == {
        datetime.datetime(2001, 12, 14, 21, 59, 43, microsecond)}


# ---------------------------------------------------------------------------
# Integration: the error surfaces while streaming a config, with its mark
# ---------------------------------------------------------------------------

def test_error_mark_locates_scalar_inside_document(Loader):
    source = (
        'schedule:\n'
        '  start: 2001-12-14 21:59:43\n'
        '  end: 2001-12-14 25:59:43\n'
    )
    with pytest.raises(TimestampOutOfRangeError) as excinfo:
        yaml.load_all(source, Loader=Loader).__next__()
    exc = excinfo.value
    assert exc.field == 'hour'
    assert exc.problem_mark is not None
    assert exc.problem_mark.line == 2
    # The snippet in str(exc) points at the bad scalar on line 3.
    assert 'line 3' in str(exc)
    assert '^' in str(exc)


def test_bad_timestamp_does_not_leak_builtin_exceptions(Loader):
    for _, valid_source, invalid_source in CONTRAST_CASES:
        # The neighbour keeps loading...
        load(valid_source, Loader)
        # ...and the bad one fails through the YAML error contract only.
        try:
            load(invalid_source, Loader)
        except yaml.YAMLError:
            pass
        except ValueError as exc:  # pragma: no cover - regression guard
            pytest.fail("bare ValueError leaked: %r" % (exc,))
        else:  # pragma: no cover - regression guard
            pytest.fail("expected a YAMLError for %r" % (invalid_source,))
