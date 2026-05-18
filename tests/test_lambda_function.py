"""Unit tests for the Lambda handler."""

import hashlib
import hmac
import json
import os

import pytest

import lambda_function
from lambda_function import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(payload: dict | None = None, headers: dict | None = None, raw_body: str | None = None) -> dict:
    """Build a minimal API Gateway / Function URL proxy event."""
    if payload is not None:
        body = json.dumps(payload)
    else:
        body = raw_body or ""
    return {
        "body": body,
        "headers": headers or {},
    }


def _sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _make_order_payload(items: list, order_id: int = 99) -> dict:
    """Build a spec-compliant order.finalized webhook payload."""
    return {
        "timestamp": "Tue, 23 Oct 2018 12:08:23 +0000",
        "event": {
            "id": 1,
            "businessId": 1,
            "createdAt": "Tue, 23 Oct 2018 12:08:23 +0000",
            "topic": "order.finalized",
            "subjectType": "order",
            "subjectId": order_id,
            "data": {
                "object": {
                    "id": order_id,
                    "items": items,
                }
            },
        },
    }


# ---------------------------------------------------------------------------
# Signature verification tests
# ---------------------------------------------------------------------------

class TestSignatureVerification:
    def test_no_secret_configured_skips_verification(self, monkeypatch):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)
        # Even with no signature header, should NOT reject the request
        payload = _make_order_payload([])
        event = _make_event(payload)
        response = handler(event, None)
        # Not a 401
        assert response["statusCode"] != 401

    def test_missing_signature_header_returns_401(self, monkeypatch):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.setenv("SHOPWIRED_WEBHOOK_SECRET", "mysecret")
        payload = _make_order_payload([])
        event = _make_event(payload)  # no signature header
        response = handler(event, None)
        assert response["statusCode"] == 401
        assert "signature" in json.loads(response["body"])["error"].lower()

    def test_invalid_signature_returns_401(self, monkeypatch):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.setenv("SHOPWIRED_WEBHOOK_SECRET", "mysecret")
        payload = _make_order_payload([])
        body = json.dumps(payload)
        event = _make_event(
            raw_body=body,
            headers={"x-shopwired-signature": "bad_signature"},
        )
        response = handler(event, None)
        assert response["statusCode"] == 401

    def test_valid_signature_passes(self, monkeypatch, mocker):
        secret = "mysecret"
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.setenv("SHOPWIRED_WEBHOOK_SECRET", secret)
        payload = _make_order_payload([])
        body = json.dumps(payload)
        sig = _sign(body, secret)
        event = {
            "body": body,
            "headers": {"x-shopwired-signature": sig},
        }
        # Patch client so no real HTTP calls happen
        mocker.patch("lambda_function.ShopwiredClient")
        response = handler(event, None)
        assert response["statusCode"] != 401


# ---------------------------------------------------------------------------
# Verification request tests
# ---------------------------------------------------------------------------

class TestVerificationRequest:
    def test_verification_request_returns_signed_token(self, monkeypatch):
        secret = "mysecret"
        monkeypatch.setenv("SHOPWIRED_WEBHOOK_SECRET", secret)
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        token = "some-verification-token"
        payload = {"timestamp": "Tue, 23 Oct 2018 12:08:23 +0000", "verificationToken": token}
        body = json.dumps(payload)
        sig = _sign(body, secret)
        event = {"body": body, "headers": {"x-shopwired-signature": sig}}
        response = handler(event, None)
        assert response["statusCode"] == 200
        expected = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        assert response["body"] == expected
        assert response["headers"]["Content-Type"] == "text/plain"

    def test_verification_request_without_secret_returns_500(self, monkeypatch):
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        payload = {"timestamp": "...", "verificationToken": "abc"}
        event = _make_event(payload)
        response = handler(event, None)
        assert response["statusCode"] == 500


# ---------------------------------------------------------------------------
# Request parsing tests
# ---------------------------------------------------------------------------

class TestRequestParsing:
    def test_invalid_json_returns_400(self, monkeypatch):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)
        event = {"body": "not-valid-json", "headers": {}}
        response = handler(event, None)
        assert response["statusCode"] == 400

    def test_empty_body_returns_400(self, monkeypatch):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)
        event = {"body": "", "headers": {}}
        response = handler(event, None)
        assert response["statusCode"] == 400

    def test_dict_body_accepted(self, monkeypatch, mocker):
        """Lambda may already decode JSON and pass a dict as body."""
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)
        mocker.patch("lambda_function.ShopwiredClient")
        payload = {
            "timestamp": "...",
            "event": {"topic": "other.event"},
        }
        event = {"body": payload, "headers": {}}
        response = handler(event, None)
        assert response["statusCode"] == 200


# ---------------------------------------------------------------------------
# Event routing tests
# ---------------------------------------------------------------------------

class TestEventRouting:
    def test_non_order_finalized_event_is_ignored(self, monkeypatch):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)
        payload = {
            "timestamp": "...",
            "event": {"topic": "order.updated", "subjectId": 5, "data": {"object": {}}},
        }
        response = handler(_make_event(payload), None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "ignored" in body["message"].lower()

    def test_order_with_no_items_returns_200(self, monkeypatch):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)
        payload = _make_order_payload([], order_id=10)
        response = handler(_make_event(payload), None)
        assert response["statusCode"] == 200
        assert "no items" in json.loads(response["body"])["message"].lower()


# ---------------------------------------------------------------------------
# Stock reduction tests
# ---------------------------------------------------------------------------

class TestStockReduction:
    def _make_order_event(self, items: list) -> dict:
        return _make_event(_make_order_payload(items))

    def test_reduces_stock_for_each_item(self, monkeypatch, mocker):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "test-key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)

        mock_client = mocker.MagicMock()
        mock_client.get_product.side_effect = [
            {"id": 1, "stock_quantity": 10},
            {"id": 2, "stock_quantity": 5},
        ]
        mocker.patch("lambda_function.ShopwiredClient", return_value=mock_client)

        items = [
            {"product_id": 1, "quantity": 3},
            {"product_id": 2, "quantity": 2},
        ]
        response = handler(self._make_order_event(items), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert len(body["updated"]) == 2

        mock_client.update_product_stock.assert_any_call(1, 7)
        mock_client.update_product_stock.assert_any_call(2, 3)

    def test_stock_does_not_go_below_zero(self, monkeypatch, mocker):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "test-key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)

        mock_client = mocker.MagicMock()
        mock_client.get_product.return_value = {"id": 1, "stock_quantity": 1}
        mocker.patch("lambda_function.ShopwiredClient", return_value=mock_client)

        items = [{"product_id": 1, "quantity": 10}]
        response = handler(self._make_order_event(items), None)

        assert response["statusCode"] == 200
        mock_client.update_product_stock.assert_called_once_with(1, 0)

    def test_partial_failure_returns_207(self, monkeypatch, mocker):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "test-key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)

        from shopwired_client import ShopwiredAPIError

        mock_client = mocker.MagicMock()
        mock_client.get_product.side_effect = [
            {"id": 1, "stock_quantity": 10},
            ShopwiredAPIError("not found", 404),
        ]
        mocker.patch("lambda_function.ShopwiredClient", return_value=mock_client)

        items = [
            {"product_id": 1, "quantity": 2},
            {"product_id": 2, "quantity": 1},
        ]
        response = handler(self._make_order_event(items), None)

        assert response["statusCode"] == 207
        body = json.loads(response["body"])
        assert len(body["updated"]) == 1
        assert len(body["errors"]) == 1
        assert body["errors"][0]["product_id"] == 2

    def test_missing_api_key_returns_500(self, monkeypatch):
        monkeypatch.delenv("SHOPWIRED_API_KEY", raising=False)
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)

        items = [{"product_id": 1, "quantity": 2}]
        response = handler(self._make_order_event(items), None)
        assert response["statusCode"] == 500

    def test_item_without_product_id_is_skipped(self, monkeypatch, mocker):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "test-key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)

        mock_client = mocker.MagicMock()
        mocker.patch("lambda_function.ShopwiredClient", return_value=mock_client)

        items = [{"quantity": 3}]  # no product_id
        response = handler(self._make_order_event(items), None)

        assert response["statusCode"] == 200
        mock_client.get_product.assert_not_called()

    def test_response_includes_previous_and_new_stock(self, monkeypatch, mocker):
        monkeypatch.setenv("SHOPWIRED_API_KEY", "test-key")
        monkeypatch.delenv("SHOPWIRED_WEBHOOK_SECRET", raising=False)

        mock_client = mocker.MagicMock()
        mock_client.get_product.return_value = {"id": 5, "stock_quantity": 20}
        mocker.patch("lambda_function.ShopwiredClient", return_value=mock_client)

        items = [{"product_id": 5, "quantity": 4}]
        response = handler(self._make_order_event(items), None)

        body = json.loads(response["body"])
        record = body["updated"][0]
        assert record["product_id"] == 5
        assert record["previous_stock"] == 20
        assert record["new_stock"] == 16

