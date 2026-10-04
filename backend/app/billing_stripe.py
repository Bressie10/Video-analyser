"""Small server-side Stripe REST adapter; tests replace only this network boundary."""

import hashlib
import hmac
import json
import os
import time

import httpx

API_VERSION = '2026-02-25.clover'


class StripeError(Exception):
    pass


def configured(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise StripeError('Billing is not configured.')
    return value


def request(method, path, *, data=None, params=None, idempotency_key=None):
    headers = {'Stripe-Version': API_VERSION}
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key
    try:
        with httpx.Client(timeout=10) as client:
            response = client.request(method, 'https://api.stripe.com/v1/' + path,
                                      auth=(configured('STRIPE_SECRET_KEY'), ''),
                                      headers=headers, data=data, params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise StripeError('Stripe is unavailable.') from exc


def create_customer(company_id):
    return request('POST', 'customers', data={'metadata[contentmetric_company_id]': str(company_id)},
                   idempotency_key='contentmetric:company:' + str(company_id) + ':customer')


def create_checkout(company_id, customer_id, price_id, origin, *, idempotency_key=None):
    data = {
        'mode': 'subscription', 'customer': customer_id,
        'line_items[0][price]': price_id, 'line_items[0][quantity]': '1',
        'client_reference_id': str(company_id),
        'metadata[contentmetric_company_id]': str(company_id),
        'subscription_data[metadata][contentmetric_company_id]': str(company_id),
        'success_url': origin + '/#settings', 'cancel_url': origin + '/#settings',
    }
    if os.environ.get('STRIPE_AUTOMATIC_TAX', '').lower() == 'true':
        data['automatic_tax[enabled]'] = 'true'
    return request('POST', 'checkout/sessions', data=data,
                   idempotency_key=idempotency_key)


def open_checkout_sessions(customer_id):
    result = request('GET', 'checkout/sessions', params={
        'customer': customer_id, 'status': 'open', 'limit': 100,
    })
    if result.get('has_more') or not isinstance(result.get('data'), list):
        raise StripeError('Checkout sessions could not be fully checked.')
    return result['data']


def current_subscriptions(customer_id):
    result = request('GET', 'subscriptions', params={
        'customer': customer_id, 'limit': 100,
    })
    if result.get('has_more') or not isinstance(result.get('data'), list):
        raise StripeError('Subscriptions could not be fully checked.')
    return result['data']


def create_portal(customer_id, origin):
    return request('POST', 'billing_portal/sessions', data={
        'customer': customer_id, 'return_url': origin + '/#settings',
    })


def retrieve_subscription(subscription_id):
    if not isinstance(subscription_id, str) or not subscription_id.startswith('sub_'):
        raise StripeError('Invalid subscription reference.')
    return request('GET', 'subscriptions/' + subscription_id)


def verify_event(body, signature, secret, *, now=None):
    """Verify Stripe's signed raw bytes with a five-minute replay window."""
    if not signature or not secret:
        raise StripeError('Invalid Stripe signature.')
    parts = dict(part.split('=', 1) for part in signature.split(',') if '=' in part)
    try:
        timestamp = int(parts['t'])
        signatures = [part[3:] for part in signature.split(',') if part.startswith('v1=')]
        if abs((now or time.time()) - timestamp) > 300 or not signatures:
            raise ValueError()
        expected = hmac.new(secret.encode(), str(timestamp).encode() + b'.' + body,
                            hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, value) for value in signatures):
            raise ValueError()
        event = json.loads(body)
        if not isinstance(event, dict) or not isinstance(event.get('data', {}).get('object'), dict):
            raise ValueError()
        return event
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise StripeError('Invalid Stripe signature.') from None
