# shopwired

AWS Lambda container that listens for [Shopwired](https://www.shopwired.net) webhook events and automatically reduces product stock when a quote is created.

## How it works

1. Shopwired sends a `quote.created` webhook POST to the Lambda Function URL (or API Gateway endpoint).
2. The handler parses the quote and iterates over each line item.
3. For each item it fetches the current `stock_quantity` from the Shopwired Products API and decrements it by the quoted quantity (flooring at 0).
4. The updated stock is written back via a `PATCH /products/{id}` request.

## Project layout

```
.
├── Dockerfile              # AWS Lambda Python 3.12 container image
├── lambda_function.py      # Lambda entry point (handler)
├── shopwired_client.py     # Thin wrapper around the Shopwired REST API
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Test / dev dependencies
└── tests/
    ├── test_lambda_function.py
    └── test_shopwired_client.py
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SHOPWIRED_API_KEY` | ✅ | Shopwired REST API key (used for HTTP Basic Auth) |
| `SHOPWIRED_WEBHOOK_SECRET` | ⬜ | If set, incoming requests are verified using the `X-Shopwired-Hmac-Sha256` HMAC header |

## Building and deploying

```bash
# Build the container image
docker build -t shopwired-webhook .

# Run locally (replace values as needed)
docker run -p 9000:8080 \
  -e SHOPWIRED_API_KEY=your_api_key \
  shopwired-webhook

# Test locally with curl
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{"body":"{\"event\":\"quote.created\",\"quote\":{\"id\":1,\"items\":[{\"product_id\":42,\"quantity\":2}]}}"}'
```

To deploy to AWS, push the image to Amazon ECR and create (or update) a Lambda function pointing at the image.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Webhook payload

The handler expects the request body to be JSON in the following shape:

```json
{
  "event": "quote.created",
  "quote": {
    "id": 123,
    "items": [
      { "product_id": 456, "quantity": 2 },
      { "product_id": 789, "quantity": 1 }
    ]
  }
}
```

Any event type other than `quote.created` is acknowledged with a 200 and ignored.

## Response codes

| Status | Meaning |
|---|---|
| 200 | All items processed successfully (or event ignored) |
| 207 | Partial success – some items failed (see `errors` array in response body) |
| 400 | Bad request (unparseable body) |
| 401 | Signature verification failed |
| 500 | Server-side configuration error (e.g. missing API key) |