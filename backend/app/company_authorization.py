"""V6 membership boundary with the existing ownership layer's lock order.

Connection -> sorted companies -> memberships -> profile advisory locks. The
connection is discovered from persisted companies, never used as app identity.
All locks and the protected operation must share one transaction.
"""
from fastapi import Depends, HTTPException, Request
from app.auth import AuthenticatedUser, require_authenticated_user
from app import auth_repository as auth


def authenticated_request(request: Request,
                          user: AuthenticatedUser = Depends(require_authenticated_user)):
    request.state.company_user = user
    return user


def authorize(db, user, company_id, *, write=False, owner=False,
              include_archived=False, target_company_id=None, connection_id=None):
    ids = sorted(set([company_id] + ([target_company_id] if target_company_id else [])), key=str)
    mode = 'UPDATE' if write else 'SHARE'
    # Initial discovery is not authorization. Re-read under company locks below;
    # binding a previously disconnected company cannot change this snapshot.
    rows = db.execute('SELECT id,connection_id FROM companies WHERE id=ANY(%s)', (ids,)).fetchall()
    connections = {row['connection_id'] for row in rows if row['connection_id']}
    if connection_id:
        connections.add(connection_id)
    for identity in sorted(connections, key=str):
        db.execute(f'SELECT id FROM meta_connections WHERE id=%s FOR {mode}', (identity,)).fetchone()
    db.execute(f'SELECT id FROM companies WHERE id=ANY(%s) ORDER BY id FOR {mode}', (ids,)).fetchall()
    try:
        companies = {}
        for identity in ids:
            check = auth.require_company_role if owner else auth.require_company_access
            companies[identity] = check(db, user.user_id, identity, include_archived=include_archived)
        if any(row['connection_id'] and row['connection_id'] not in connections for row in companies.values()):
            raise HTTPException(409, 'Company connection changed; retry the request.')
        return companies[company_id]
    except auth.CompanyAccessDenied:
        raise HTTPException(403, 'Company access denied.') from None
