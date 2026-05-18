"""Unit tests for ShopwiredClient."""

import pytest
import responses as resp
import requests

from shopwired_client import ShopwiredClient, ShopwiredAPIError, BASE_URL


@pytest.fixture
def client():
    return ShopwiredClient(api_key="test-api-key")


class TestShopwiredClientInit:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="api_key"):
            ShopwiredClient(api_key="")

    def test_uses_default_base_url(self, client):
        assert client._base_url == BASE_URL.rstrip("/")

    def test_accepts_custom_base_url(self):
        c = ShopwiredClient(api_key="key", base_url="https://example.com/api")
        assert c._base_url == "https://example.com/api"

    def test_strips_trailing_slash_from_base_url(self):
        c = ShopwiredClient(api_key="key", base_url="https://example.com/api/")
        assert c._base_url == "https://example.com/api"


class TestGetProduct:
    @resp.activate
    def test_returns_product_on_success(self, client):
        product = {"id": 42, "name": "Widget", "stock_quantity": 10}
        resp.add(
            resp.GET,
            f"{BASE_URL}/products/42",
            json=product,
            status=200,
        )
        result = client.get_product(42)
        assert result == product

    @resp.activate
    def test_raises_on_404(self, client):
        resp.add(resp.GET, f"{BASE_URL}/products/99", json={"error": "not found"}, status=404)
        with pytest.raises(ShopwiredAPIError) as exc_info:
            client.get_product(99)
        assert exc_info.value.status_code == 404

    @resp.activate
    def test_raises_on_500(self, client):
        resp.add(resp.GET, f"{BASE_URL}/products/1", json={}, status=500)
        with pytest.raises(ShopwiredAPIError) as exc_info:
            client.get_product(1)
        assert exc_info.value.status_code == 500

    @resp.activate
    def test_raises_on_network_error(self, client):
        resp.add(resp.GET, f"{BASE_URL}/products/1", body=requests.ConnectionError("timeout"))
        with pytest.raises(ShopwiredAPIError, match="Network error"):
            client.get_product(1)

    @resp.activate
    def test_uses_basic_auth(self, client):
        product = {"id": 1, "stock_quantity": 5}
        resp.add(resp.GET, f"{BASE_URL}/products/1", json=product, status=200)
        client.get_product(1)
        assert resp.calls[0].request.headers["Authorization"].startswith("Basic ")


class TestUpdateProductStock:
    @resp.activate
    def test_patches_stock_quantity(self, client):
        updated = {"id": 42, "stock_quantity": 8}
        resp.add(resp.PATCH, f"{BASE_URL}/products/42", json=updated, status=200)
        result = client.update_product_stock(42, 8)
        assert result == updated

        # Verify the request body contains the new stock value
        import json
        sent_body = json.loads(resp.calls[0].request.body)
        assert sent_body == {"stock_quantity": 8}

    @resp.activate
    def test_raises_on_4xx(self, client):
        resp.add(resp.PATCH, f"{BASE_URL}/products/42", json={}, status=422)
        with pytest.raises(ShopwiredAPIError) as exc_info:
            client.update_product_stock(42, 5)
        assert exc_info.value.status_code == 422

    @resp.activate
    def test_raises_on_network_error(self, client):
        resp.add(
            resp.PATCH,
            f"{BASE_URL}/products/42",
            body=requests.ConnectionError("reset"),
        )
        with pytest.raises(ShopwiredAPIError, match="Network error"):
            client.update_product_stock(42, 5)
