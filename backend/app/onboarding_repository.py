"""Derived onboarding health over verified user membership and company scope."""

from app import auth_repository
from app.meta_library_repository import ANALYSIS_VERSION

STEPS = ('workspace', 'meta', 'account', 'analysis', 'idea')


def get_state(db, user_id):
    # One bounded statement. Candidate company flags are computed only for the
    # caller's active memberships. No read writes a fallback anchor.
    row = db.execute('''
        WITH state AS (
            SELECT onboarding_company_id,welcome_seen_at,onboarding_skipped_at
            FROM user_onboarding_state WHERE user_id=%(user_id)s
        ), candidates AS (
            SELECT c.id,c.created_at,c.connection_id,
                EXISTS (
                    SELECT 1 FROM company_accounts ca JOIN meta_accounts a
                      ON a.id=ca.account_id AND a.connection_id=ca.connection_id
                    WHERE ca.company_id=c.id AND ca.connection_id=c.connection_id
                      AND ca.account_platform IN ('facebook','instagram')
                      AND a.platform=ca.account_platform
                ) AS account,
                EXISTS (
                    SELECT 1 FROM meta_library_items i
                    JOIN meta_accounts a ON a.id=i.account_id AND a.connection_id=i.connection_id
                    JOIN videos v ON v.id=i.video_id AND v.meta_connection_id=i.connection_id
                    WHERE i.connection_id=c.connection_id
                      AND i.content_type<>'ad'
                      AND i.analysis_state='completed'
                      AND i.analysis_version=%(version)s
                      AND v.analysis_version=i.analysis_version
                      AND (
                        EXISTS (
                            SELECT 1 FROM company_accounts ca
                            WHERE ca.company_id=c.id AND ca.connection_id=i.connection_id
                              AND ca.account_id=i.account_id
                              AND ca.account_platform IN ('facebook','instagram')
                        ) OR EXISTS (
                            SELECT 1 FROM meta_ad_assets edge
                            JOIN meta_library_items ad ON ad.id=edge.ad_item_id
                            JOIN company_ad_assignments x ON x.ad_item_id=ad.id
                            WHERE edge.video_item_id=i.id AND ad.connection_id=i.connection_id
                              AND ad.content_type='ad' AND x.company_id=c.id
                              AND x.connection_id=ad.connection_id AND x.account_id=ad.account_id
                        )
                      )
                ) AS analysis,
                EXISTS (SELECT 1 FROM ideas idea WHERE idea.company_id=c.id) AS idea
            FROM company_memberships m JOIN companies c ON c.id=m.company_id
            WHERE m.user_id=%(user_id)s AND c.archived_at IS NULL
        )
        SELECT chosen.id AS company_id,chosen.account,chosen.analysis,chosen.idea,
               s.welcome_seen_at IS NOT NULL AS welcome_seen,
               s.onboarding_skipped_at IS NOT NULL AS skipped,
               EXISTS (SELECT 1 FROM candidates) AS workspace,
               EXISTS (SELECT 1 FROM meta_connections mc
                       WHERE mc.owner_user_id=%(user_id)s AND mc.status='connected'
                         AND mc.token_ciphertext IS NOT NULL AND mc.expires_at>now()) AS meta
        FROM (SELECT 1) seed
        LEFT JOIN state s ON true
        LEFT JOIN LATERAL (
            SELECT candidate.* FROM candidates candidate
            ORDER BY (candidate.id=s.onboarding_company_id) DESC NULLS LAST,
                     (candidate.account::int+candidate.analysis::int+candidate.idea::int) DESC,
                     candidate.created_at,candidate.id LIMIT 1
        ) chosen ON true
    ''', {'user_id': user_id, 'version': ANALYSIS_VERSION}).fetchone()
    steps = {key: bool(row[key]) for key in STEPS}
    next_step = next((key for key in STEPS if not steps[key]), None)
    return {'company_id': row['company_id'], 'welcome_seen': row['welcome_seen'],
            'skipped': row['skipped'], 'progress': 20 * sum(steps.values()),
            'complete': next_step is None, 'next_step': next_step, 'steps': steps}


def mark(db, user_id, column):
    if column not in ('welcome_seen_at', 'onboarding_skipped_at'):
        raise ValueError('Unsupported onboarding field.')
    auth_repository.ensure_profile(db, user_id)
    db.execute(f'''INSERT INTO user_onboarding_state(user_id,{column}) VALUES (%s,now())
        ON CONFLICT (user_id) DO UPDATE SET {column}=COALESCE(user_onboarding_state.{column},EXCLUDED.{column}),
        updated_at=CASE WHEN user_onboarding_state.{column} IS NULL THEN now()
                        ELSE user_onboarding_state.updated_at END''', (user_id,))
    return get_state(db, user_id)


def select_company(db, user_id, company_id):
    auth_repository.require_company_access(db, user_id, company_id)
    auth_repository.ensure_profile(db, user_id)
    db.execute('''INSERT INTO user_onboarding_state(user_id,onboarding_company_id)
        VALUES (%s,%s) ON CONFLICT (user_id) DO UPDATE
        SET onboarding_company_id=EXCLUDED.onboarding_company_id,
            updated_at=CASE WHEN user_onboarding_state.onboarding_company_id
                                  IS DISTINCT FROM EXCLUDED.onboarding_company_id THEN now()
                            ELSE user_onboarding_state.updated_at END''', (user_id, company_id))
    return get_state(db, user_id)
