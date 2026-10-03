"""Authenticated company billing and signature-only Stripe webhook routes."""

import os
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.auth import AuthenticatedUser, require_authenticated_user
from app.auth_dependencies import application_database
from app import auth_repository as auth, billing_repository as billing, billing_stripe as stripe

router = APIRouter(tags=['company billing'])


def origin():
    value = stripe.configured('APP_ORIGIN').rstrip('/')
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise stripe.StripeError('Invalid application origin.')
    return value


def unavailable():
    return HTTPException(503, 'Billing is unavailable.')


def destination(value, host):
    parsed = urlparse(value or '')
    if parsed.scheme != 'https' or parsed.hostname != host:
        raise stripe.StripeError('Invalid billing destination.')
    return {'url': value}


@router.get('/api/companies/{company_id}/billing')
def read_billing(company_id: UUID, user: AuthenticatedUser = Depends(require_authenticated_user)):
    with application_database() as db:
        company = auth.require_company_access(db, user.user_id, company_id)
        row = billing.initialize(db, company_id)
        return JSONResponse(jsonable_encoder(billing.snapshot(
            db, row, can_manage_billing=company['role'] == 'owner')),
            headers={'Cache-Control': 'private, no-store'})


@router.post('/api/companies/{company_id}/billing/checkout')
def checkout(company_id: UUID, user: AuthenticatedUser = Depends(require_authenticated_user)):
    try:
        price = stripe.configured('STRIPE_PRO_MONTHLY_PRICE_ID')
        if not price.startswith('price_'):
            raise stripe.StripeError('Invalid Pro price.')
        return_origin = origin()
        with application_database() as db:
            auth.require_company_role(db, user.user_id, company_id)
            row = billing.initialize(db, company_id)
            if billing.effective_plan(row) == 'pro':
                raise HTTPException(409, 'Manage the current subscription in the billing portal.')
            customer = row['stripe_customer_id']
            if not customer:
                customer = stripe.create_customer(company_id)['id']
                db.execute('''UPDATE company_billing SET stripe_customer_id=%s,updated_at=now()
                    WHERE company_id=%s''', (customer, company_id))
            session = stripe.create_checkout(company_id, customer, price, return_origin,
                idempotency_key=f'contentmetric:company:{company_id}:checkout:{row["current_period_start"].isoformat()}')
            return destination(session.get('url'), 'checkout.stripe.com')
    except stripe.StripeError:
        raise unavailable() from None


@router.post('/api/companies/{company_id}/billing/portal')
def portal(company_id: UUID, user: AuthenticatedUser = Depends(require_authenticated_user)):
    try:
        return_origin = origin()
        with application_database() as db:
            auth.require_company_role(db, user.user_id, company_id)
            row = billing.initialize(db, company_id)
            if not row['stripe_customer_id']:
                raise HTTPException(409, 'No billing customer exists for this company.')
            session = stripe.create_portal(row['stripe_customer_id'], return_origin)
            return destination(session.get('url'), 'billing.stripe.com')
    except stripe.StripeError:
        raise unavailable() from None


def process_event(db, event):
    event_id, event_type = event.get('id'), event.get('type')
    if not isinstance(event_id, str) or not event_id.startswith('evt_'):
        raise ValueError('Invalid event ID.')
    claimed = db.execute('''INSERT INTO stripe_webhook_events(event_id,event_type)
        VALUES (%s,%s) ON CONFLICT(event_id) DO NOTHING RETURNING event_id''',
        (event_id, event_type)).fetchone()
    if not claimed:
        return False
    obj = event['data']['object']
    supported = {'checkout.session.completed', 'customer.subscription.created',
                 'customer.subscription.updated', 'customer.subscription.deleted',
                 'invoice.paid', 'invoice.payment_failed'}
    if event_type in supported:
        customer = obj.get('customer')
        row = db.execute('SELECT * FROM company_billing WHERE stripe_customer_id=%s FOR UPDATE',
                         (customer,)).fetchone()
        if row is None:
            raise ValueError('Unknown company billing customer.')
        company_id = str(row['company_id'])
        metadata = obj.get('metadata') or {}
        reference = metadata.get('contentmetric_company_id') or obj.get('client_reference_id')
        if reference and reference != company_id:
            raise ValueError('Company metadata mismatch.')
        if event_type == 'checkout.session.completed':
            if obj.get('mode') != 'subscription' or not obj.get('subscription'):
                raise ValueError('Invalid Checkout session.')
            subscription = stripe.retrieve_subscription(obj['subscription'])
        elif event_type == 'customer.subscription.deleted':
            subscription = obj
        elif event_type.startswith('customer.subscription.'):
            subscription = stripe.retrieve_subscription(obj['id'])
        else:
            subscription_id = obj.get('subscription') or (obj.get('parent') or {}).get('subscription_details', {}).get('subscription')
            if not subscription_id:
                raise ValueError('Invoice subscription missing.')
            subscription = stripe.retrieve_subscription(subscription_id)
        if event_type == 'customer.subscription.deleted':
            if row['plan_code'] == 'pro' and row['stripe_subscription_id'] == subscription.get('id'):
                billing.start_free(db, row, at=billing.datetime.now(billing.timezone.utc), status='canceled')
        else:
            billing.apply_subscription(db, row, subscription,
                                       price_id=stripe.configured('STRIPE_PRO_MONTHLY_PRICE_ID'))
    return True


@router.post('/api/stripe/webhook')
async def webhook(request: Request):
    body = await request.body()
    try:
        event = stripe.verify_event(body, request.headers.get('Stripe-Signature'),
                                    stripe.configured('STRIPE_WEBHOOK_SECRET'))
    except stripe.StripeError:
        raise HTTPException(400, 'Invalid Stripe signature.') from None
    try:
        with application_database() as db:
            processed = process_event(db, event)
        return {'received': True, 'processed': processed}
    except (ValueError, KeyError, TypeError, stripe.StripeError):
        raise unavailable() from None
