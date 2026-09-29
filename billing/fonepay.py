"""Fonepay Checkout (Intent / dynamic QR) client.

Protocol, per Fonepay's "Checkout Intent Flow" v1.10 document:

1. POST {API}/login with HTTP Basic auth (username:password) and a
   `signature` header -> accessToken ("Bearer ...", valid `expiresIn` s).
2. Every request carries `signature`: Base64(SHA256withRSA(exact request
   body)) made with the merchant's PKCS#8 private key, and (after login)
   `Authorization: <accessToken>`.
3. POST {API}/generate-intent-qr {amount, billId, terminalId, paymentMode,
   referenceLabel, qrType: INTENT_QR} -> qrMessage/qrString (shown as a QR,
   or passed to a bank app deep link) + websocketId (live status socket).
4. GET {API}/banks/list (header paymentMode: INTENT) -> bank apps with
   their deep-link intentScheme.
5. POST {API}/thirdPartyDynamicQrGetStatus {terminalId, referenceLabel} ->
   paymentStatus success/pending/failed. This server-side check is the only
   thing that grants access — WebSocket messages are just a hint to check.

Every call raises FonepayError on transport/HTTP/response problems, so
callers have one exception to handle.
"""
import base64
import json
import logging

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

TOKEN_CACHE_KEY = 'billing:fonepay:token'
TIMEOUT_SECONDS = 20


class FonepayError(Exception):
    """Anything that went wrong talking to Fonepay."""


def is_configured() -> bool:
    return all([
        settings.FONEPAY_API_URL, settings.FONEPAY_USERNAME, settings.FONEPAY_PASSWORD,
        settings.FONEPAY_PRIVATE_KEY, settings.FONEPAY_TERMINAL_ID,
    ])


def _private_key():
    raw = ''.join(settings.FONEPAY_PRIVATE_KEY.split())
    try:
        der = bytes.fromhex(raw) if all(c in '0123456789abcdefABCDEF' for c in raw) else base64.b64decode(raw)
        return serialization.load_der_private_key(der, password=None)
    except Exception as exc:  # malformed key is a configuration error
        raise FonepayError('FONEPAY_PRIVATE_KEY is not a valid Base64/hex PKCS#8 RSA key.') from exc


def sign(payload: str) -> str:
    """Base64(SHA256withRSA(payload)) — Fonepay's `signature` header."""
    signature = _private_key().sign(payload.encode('utf-8'), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode('ascii')


def _body(data: dict) -> str:
    # The signature covers these exact bytes, so the same string is both
    # signed and sent (never re-serialised by requests).
    return json.dumps(data, separators=(',', ':'))


def _url(path: str) -> str:
    return f'{settings.FONEPAY_API_URL}/{path}'


def _parse(response) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise FonepayError(f'Fonepay returned a non-JSON response (HTTP {response.status_code}).') from exc
    if response.status_code >= 400:
        message = data.get('message') if isinstance(data, dict) else None
        raise FonepayError(f'Fonepay error (HTTP {response.status_code}): {message or data}')
    return data


def _request(method: str, path: str, *, data: dict | None = None, headers: dict | None = None) -> dict:
    body = _body(data) if data is not None else ''
    all_headers = {'Content-Type': 'application/json', 'signature': sign(body), **(headers or {})}
    try:
        response = requests.request(method, _url(path), data=body or None, headers=all_headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise FonepayError(f'Could not reach Fonepay: {exc.__class__.__name__}') from exc
    return _parse(response)


def access_token(force_refresh: bool = False) -> str:
    """Logs in (cached until shortly before the token expires)."""
    if not force_refresh:
        token = cache.get(TOKEN_CACHE_KEY)
        if token:
            return token
    credentials = f'{settings.FONEPAY_USERNAME}:{settings.FONEPAY_PASSWORD}'.encode('utf-8')
    data = _request('POST', 'login', data={
        'username': settings.FONEPAY_USERNAME, 'password': settings.FONEPAY_PASSWORD,
    }, headers={'Authorization': 'Basic ' + base64.b64encode(credentials).decode('ascii')})
    token = data.get('accessToken')
    if not token:
        raise FonepayError('Fonepay login succeeded but returned no access token.')
    if not token.lower().startswith('bearer '):
        token = f'Bearer {token}'
    lifetime = int(data.get('expiresIn') or 3600)
    cache.set(TOKEN_CACHE_KEY, token, max(lifetime - 120, 60))
    return token


def _authorised(method: str, path: str, **kwargs) -> dict:
    """An authenticated call; retries once with a fresh token on 401."""
    extra_headers = kwargs.pop('headers', {})
    for attempt in (1, 2):
        headers = {'Authorization': access_token(force_refresh=attempt == 2), **extra_headers}
        try:
            return _request(method, path, headers=headers, **kwargs)
        except FonepayError as exc:
            if attempt == 1 and 'HTTP 401' in str(exc):
                continue
            raise
    raise FonepayError('Fonepay authentication failed.')


def generate_intent_qr(amount, bill_id: str, reference: str) -> dict:
    """Creates a single-use payment request. `reference` must be unique,
    alphanumeric, max 30 chars; amount 1–9,999,999."""
    return _authorised('POST', 'generate-intent-qr', data={
        'amount': float(amount), 'billId': bill_id[:50], 'terminalId': settings.FONEPAY_TERMINAL_ID,
        'paymentMode': 'QR', 'referenceLabel': reference, 'qrType': 'INTENT_QR',
    })


def bank_list() -> list[dict]:
    """Bank apps that support Fonepay Checkout (name, icon, intentScheme, packageName)."""
    cache_key = 'billing:fonepay:banks'
    banks = cache.get(cache_key)
    if banks is None:
        data = _authorised('GET', 'banks/list', headers={'paymentMode': 'INTENT'})
        banks = data.get('bankDetails', []) if isinstance(data, dict) else []
        cache.set(cache_key, banks, 3600)
    return banks


def payment_status(reference: str) -> dict:
    """{'paymentStatus': 'success'|'pending'|'failed', 'fonepayTraceId', ...}."""
    return _authorised('POST', 'thirdPartyDynamicQrGetStatus', data={
        'terminalId': settings.FONEPAY_TERMINAL_ID, 'referenceLabel': reference,
    })
