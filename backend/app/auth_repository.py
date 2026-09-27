"""Application identities and memberships. User IDs must come from auth.py.

Authorization locks last until the caller commits. Check access and perform the
protected read/write in the SAME transaction, including after long model calls.
"""

from uuid import UUID


class CompanyAccessDenied(LookupError):
    pass


def ensure_profile(db, user_id: UUID):
    db.execute('INSERT INTO user_profiles(user_id) VALUES (%s) ON CONFLICT DO NOTHING', (user_id,))
    return db.execute('SELECT display_name FROM user_profiles WHERE user_id=%s', (user_id,)).fetchone()


def list_accessible_companies(db, user_id: UUID, *, include_archived=False):
    return db.execute('''SELECT c.id,c.name,c.created_at,c.archived_at,m.role
        FROM company_memberships m JOIN companies c ON c.id=m.company_id
        WHERE m.user_id=%s AND (%s OR c.archived_at IS NULL)
        ORDER BY c.created_at,c.id''', (user_id, include_archived)).fetchall()


def require_company_access(db, user_id: UUID, company_id: UUID, *, include_archived=False):
    row = db.execute('''SELECT c.id,c.name,c.connection_id,c.archived_at,m.role
        FROM companies c JOIN company_memberships m ON m.company_id=c.id
        WHERE c.id=%s AND m.user_id=%s AND (%s OR c.archived_at IS NULL)
        FOR SHARE OF c,m''', (company_id, user_id, include_archived)).fetchone()
    if row is None:
        raise CompanyAccessDenied()
    return row


def require_company_role(db, user_id: UUID, company_id: UUID, *, role='owner', include_archived=False):
    if role not in ('owner', 'member'):
        raise ValueError('Unsupported company role.')
    company = require_company_access(db, user_id, company_id, include_archived=include_archived)
    if company['role'] != role:
        raise CompanyAccessDenied()
    return company


def create_company_for_user(db, user_id: UUID, name: str):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise ValueError('Company name must contain 1–200 characters.')
    # A nested transaction is a savepoint: even a caller catching a membership
    # failure cannot accidentally commit a half-created company.
    with db.transaction():
        ensure_profile(db, user_id)
        company = db.execute('INSERT INTO companies(name) VALUES (%s) RETURNING id,name,created_at,archived_at',
                             (name.strip(),)).fetchone()
        db.execute("INSERT INTO company_memberships(company_id,user_id,role) VALUES (%s,%s,'owner')",
                   (company['id'], user_id))
        return {**company, 'role': 'owner'}


def require_owned_meta_connection(db, user_id: UUID, connection_id: UUID):
    """Agent C must use this before reconnect/disconnect; NULL is never claimed."""
    row = db.execute('''SELECT id FROM meta_connections
        WHERE id=%s AND owner_user_id=%s FOR SHARE''', (connection_id, user_id)).fetchone()
    if row is None:
        raise CompanyAccessDenied()
    return row


def create_owned_meta_connection(db, user_id: UUID, external_user_id: str,
                                 token_ciphertext: str, expires_at):
    """Insert only. A duplicate provider identity must NOT upsert/claim legacy data.

    Caller (Agent C) encrypts the provider token with library.cipher(), handles
    conflict, creates provider session/jobs in its outer transaction.
    """
    with db.transaction():
        ensure_profile(db, user_id)
        return db.execute('''INSERT INTO meta_connections
            (owner_user_id,external_user_id,token_ciphertext,expires_at)
            VALUES (%s,%s,%s,%s) RETURNING id,owner_user_id''',
            (user_id, external_user_id, token_ciphertext, expires_at)).fetchone()
