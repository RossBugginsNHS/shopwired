"""AWS Lambda handler for Shopwired webhooks.

Processes ``quote.created`` events and reduces product stock by the quantity
specified in each quote line item.

Environment variables
---------------------
SHOPWIRED_API_KEY
    Shopwired REST API key (required).
SHOPWIRED_WEBHOOK_SECRET
    If set, incoming webhook requests are verified using the
    ``X-Shopwired-Hmac-Sha256`` header (optional but recommended).
"""

import hashlib
import hmac
import json
import logging
import os

from shopwired_client import ShopwiredAPIError, ShopwiredClient

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EVENT_QUOTE_CREATED = "quote.created"


def _verify_signature(body: str, signature_header: str, secret: str) -> bool:
    """Return True if the HMAC-SHA256 signature in *signature_header* matches.

    Shopwired signs webhook payloads with the webhook secret and sends the
    hex-encoded digest in the ``X-Shopwired-Hmac-Sha256`` header.
    """
    expected = hmac.new(
        secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _parse_body(event: dict) -> dict | None:
    """Parse and return the JSON body from a Lambda event.

    Returns ``None`` if the body is absent or cannot be decoded.
    """
    raw = event.get("body") or ""
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _get_headers(event: dict) -> dict:
    """Return a lower-cased header dict from a Lambda event."""
    headers = event.get("headers") or {}
    return {k.lower(): v for k, v in headers.items()}


def _json_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event: dict, context) -> dict:  # noqa: ANN001
    """Lambda entry point.

    Expects an *event* shaped like an API Gateway / Function URL proxy event
    (or the raw Lambda invocation payload with a ``body`` key).
    """
    headers = _get_headers(event)

    # ── Optional webhook signature verification ──────────────────────────────
    webhook_secret = os.environ.get("SHOPWIRED_WEBHOOK_SECRET", "")
    if webhook_secret:
        raw_body = event.get("body") or ""
        sig = headers.get("x-shopwired-hmac-sha256", "")
        if not sig:
            logger.warning("Missing webhook signature header")
            return _json_response(401, {"error": "Missing signature"})
        if not _verify_signature(raw_body, sig, webhook_secret):
            logger.warning("Webhook signature verification failed")
            return _json_response(401, {"error": "Invalid signature"})

    # ── Parse body ───────────────────────────────────────────────────────────
    payload = _parse_body(event)
    if payload is None:
        logger.error("Could not parse webhook payload")
        return _json_response(400, {"error": "Invalid or missing JSON body"})

    # ── Route by event type ──────────────────────────────────────────────────
    event_type = payload.get("event")
    if event_type != EVENT_QUOTE_CREATED:
        logger.info("Ignoring event type: %s", event_type)
        return _json_response(200, {"message": f"Event '{event_type}' ignored"})

    # ── Process quote.created ────────────────────────────────────────────────
    quote = payload.get("quote") or {}
    quote_id = quote.get("id", "<unknown>")
    items = quote.get("items") or []

    logger.info("Processing quote.created event for quote id=%s (%d items)", quote_id, len(items))

    if not items:
        return _json_response(200, {"message": "Quote has no items"})

    # ── Initialise API client ────────────────────────────────────────────────
    api_key = os.environ.get("SHOPWIRED_API_KEY", "")
    if not api_key:
        logger.error("SHOPWIRED_API_KEY environment variable is not set")
        return _json_response(500, {"error": "Server configuration error"})

    client = ShopwiredClient(api_key=api_key)

    updated: list[dict] = []
    errors: list[dict] = []

    for item in items:
        product_id = item.get("product_id")
        quantity = item.get("quantity", 0)

        if not product_id:
            logger.warning("Skipping item with missing product_id in quote %s", quote_id)
            continue

        try:
            product = client.get_product(product_id)
            current_stock = int(product.get("stock_quantity", 0))
            new_stock = max(0, current_stock - int(quantity))

            client.update_product_stock(product_id, new_stock)

            logger.info(
                "quote=%s product=%s stock %d → %d",
                quote_id,
                product_id,
                current_stock,
                new_stock,
            )
            updated.append(
                {
                    "product_id": product_id,
                    "previous_stock": current_stock,
                    "new_stock": new_stock,
                }
            )

        except ShopwiredAPIError as exc:
            logger.error(
                "API error updating product %s for quote %s: %s",
                product_id,
                quote_id,
                exc,
            )
            errors.append({"product_id": product_id, "error": str(exc)})

    if errors:
        return _json_response(207, {"updated": updated, "errors": errors})

    return _json_response(200, {"updated": updated})
