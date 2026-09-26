"""Ad-level Meta Insights for Facebook/Instagram delivery, using the Meta User token."""

from datetime import date
import json
import re

from app.ad_metrics import (
    ACTION_FIELDS, ATTRIBUTION_WINDOWS, DECIMAL_FIELDS, INTEGER_FIELDS,
    has_ad_values, integer, normalize_ad_metrics,
)
from app.meta import MetaClient, MetaError
from app.performance import VideoPerformance, performance_snapshot

FIELDS = ('ad_id', 'account_id', 'account_currency', 'date_start', 'date_stop',
          *INTEGER_FIELDS, *DECIMAL_FIELDS, *ACTION_FIELDS)


class AdMetricsUnavailable(ValueError):
    pass


def ad_performance(client: MetaClient, ad_id: str, since: date, until: date) -> VideoPerformance:
    if not re.fullmatch(r'[0-9]{1,30}', ad_id) or since > until:
        raise ValueError('Provide a numeric Meta ad ID and an ordered date range.')
    ad = client.get(ad_id, {'fields': 'id,account_id'})
    if ad.get('id') != ad_id or not isinstance(ad.get('account_id'), str) or not re.fullmatch(r'[0-9]{1,30}', ad['account_id']):
        raise MetaError('Meta returned an invalid ad identity.')
    payload = client.get(f'{ad_id}/insights', {
        'fields': ','.join(FIELDS), 'level': 'ad',
        'time_range': json.dumps({'since': since.isoformat(), 'until': until.isoformat()}),
        'time_increment': 'all_days', 'action_report_time': 'impression',
        'action_attribution_windows': json.dumps(list(ATTRIBUTION_WINDOWS)),
        'action_breakdowns': 'action_type', 'limit': 1,
    })
    rows = payload.get('data')
    if rows == []:
        raise AdMetricsUnavailable('Meta has no ad metrics for this reporting period.')
    paging = payload.get('paging', {})
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(paging, dict) or paging.get('next')):
        raise MetaError('Meta returned an unexpected ad report shape.')
    row = rows[0]
    if (row.get('ad_id') != ad_id or row.get('account_id') != ad['account_id']
            or row.get('date_start') != since.isoformat() or row.get('date_stop') != until.isoformat()):
        raise MetaError('Meta returned insights for a different ad, account, or reporting range.')
    try:
        details = normalize_ad_metrics({
            **row, 'action_report_time': 'impression',
            'action_attribution_windows': list(ATTRIBUTION_WINDOWS),
        })
        if not has_ad_values(details):
            raise AdMetricsUnavailable('Meta has no available ad metrics for this reporting period.')
        # The video_view action is Meta's 3-second video view, not impressions or starts.
        view = next((r['value'] for r in details['actions'] or [] if r['action_type'] == 'video_view'), None)
        return performance_snapshot('meta_ads', {'view_count': integer(view), 'meta_ads': details})
    except AdMetricsUnavailable:
        raise
    except ValueError:
        raise MetaError('Meta returned invalid ad performance values.') from None
