"""Validated, allowlisted ad-specific data for the common performance contract."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
import re

INTEGER_FIELDS = ('impressions', 'reach', 'clicks')
DECIMAL_FIELDS = ('spend', 'ctr', 'cpc')
ACTION_FIELDS = ('actions', 'conversions', 'video_play_actions')
ATTRIBUTION_WINDOWS = ('7d_click', '1d_view')


def decimal_string(value: object) -> str | None:
    """Keep monetary/rate/modeled values exact and JSON-safe, without rounding."""
    if value is None:
        return None
    if type(value) not in (str, int) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', str(value)):
        raise ValueError('Ad values must be non-negative decimal strings or integers.')
    if len(str(value)) > 60:
        raise ValueError('Ad value is too large.')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('Invalid ad value.') from None
    return format(number, 'f')


def integer(value: object) -> int | None:
    normalized = decimal_string(value)
    if normalized is None:
        return None
    number = Decimal(normalized)
    if number != number.to_integral_value() or number > 9223372036854775807:
        raise ValueError('Ad count must be a non-negative BIGINT integer.')
    return int(number)


def action_stats(value: object) -> list[dict] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError('Invalid ad action stats.')
    rows, seen = [], set()
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError('Invalid ad action.')
        name = row.get('action_type')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', name) or name in seen:
            raise ValueError('Invalid or duplicate ad action type.')
        seen.add(name)
        # Preserve attribution-window values separately; never sum overlapping actions/windows.
        rows.append({'action_type': name, **{
            key: decimal_string(row.get(key)) for key in ('value', *ATTRIBUTION_WINDOWS)
        }})
    return rows


def normalize_ad_metrics(values: object) -> dict:
    if not isinstance(values, Mapping):
        raise ValueError('Meta Ads details must be an object.')
    result = {key: integer(values.get(key)) for key in INTEGER_FIELDS}
    result.update({key: decimal_string(values.get(key)) for key in DECIMAL_FIELDS})
    result.update({key: action_stats(values.get(key)) for key in ACTION_FIELDS})
    for key in ('date_start', 'date_stop'):
        value = values.get(key)
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('Ad metrics require a reporting date range.')
        result[key] = date.fromisoformat(value).isoformat()
    if result['date_start'] > result['date_stop']:
        raise ValueError('Invalid ad reporting range.')
    currency = values.get('account_currency')
    if currency is not None and (not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency)):
        raise ValueError('Invalid ad currency.')
    result['account_currency'] = currency
    if values.get('action_report_time') != 'impression' or values.get('action_attribution_windows') != list(ATTRIBUTION_WINDOWS):
        raise ValueError('Unexpected ad attribution context.')
    result['action_report_time'] = 'impression'
    result['action_attribution_windows'] = list(ATTRIBUTION_WINDOWS)
    return result


def has_ad_values(values: dict) -> bool:
    return any(values[key] is not None for key in (*INTEGER_FIELDS, *DECIMAL_FIELDS)) or any(
        row[key] is not None for field in ACTION_FIELDS for row in values[field] or []
        for key in ('value', *ATTRIBUTION_WINDOWS)
    )
