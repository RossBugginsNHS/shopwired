"""Client for the Shopwired REST API."""

import logging

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.shopwired.com/v1"


class ShopwiredAPIError(Exception):
    """Raised when the Shopwired API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ShopwiredClient:
    """Minimal Shopwired REST API client.

    Authentication uses HTTP Basic Auth: the API key is the username and the
    password is always ``"x"`` (as documented by Shopwired).
    """

    def __init__(self, api_key: str, base_url: str = BASE_URL):
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.auth = (api_key, "x")
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def get_product(self, product_id: str | int) -> dict:
        """Return the product resource for *product_id*.

        Raises :class:`ShopwiredAPIError` on non-2xx responses.
        """
        url = f"{self._base_url}/products/{product_id}"
        logger.debug("GET %s", url)
        try:
            response = self._session.get(url)
        except requests.RequestException as exc:
            raise ShopwiredAPIError(f"Network error fetching product {product_id}: {exc}") from exc

        if not response.ok:
            raise ShopwiredAPIError(
                f"Failed to get product {product_id}: HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return response.json()

    def update_product_stock(self, product_id: str | int, stock_quantity: int) -> dict:
        """Set the stock quantity for *product_id* to *stock_quantity*.

        Raises :class:`ShopwiredAPIError` on non-2xx responses.
        """
        url = f"{self._base_url}/products/{product_id}"
        logger.debug("PATCH %s  stock_quantity=%d", url, stock_quantity)
        try:
            response = self._session.patch(url, json={"stock_quantity": stock_quantity})
        except requests.RequestException as exc:
            raise ShopwiredAPIError(
                f"Network error updating stock for product {product_id}: {exc}"
            ) from exc

        if not response.ok:
            raise ShopwiredAPIError(
                f"Failed to update stock for product {product_id}: HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return response.json()
