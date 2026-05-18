# shopwired

AWS Lambda container that listens for [Shopwired](https://www.shopwired.net) webhook events and automatically reduces product stock when an order is finalised.

## How it works

1. Shopwired sends an `order.finalized` webhook POST to the Lambda Function URL (or API Gateway endpoint).
2. The handler optionally verifies the `X-ShopWired-Signature` header, then parses the payload.
3. On first setup, Shopwired sends a verification request; the handler responds with the HMAC-SHA256 of the `verificationToken`.
4. For `order.finalized` events the handler iterates over each order line item.
5. For each item it fetches the current `stock_quantity` from the Shopwired Products API and decrements it by the ordered quantity (flooring at 0).
6. The updated stock is written back via a `PATCH /products/{id}` request.

## Project layout

```
.
├── Dockerfile              # AWS Lambda Python 3.12 container image
├── docker-compose.yml      # Local development with Docker Compose
├── local_server.py         # HTTP adapter for local dev (used by docker-compose)
├── sst.config.ts           # Serverless Stack (SST) deployment configuration
├── package.json            # SST dev dependency
├── lambda_function.py      # Lambda entry point (handler)
├── shopwired_client.py     # Thin wrapper around the Shopwired REST API
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Test / dev dependencies
├── .env.example            # Environment variable template
└── tests/
    ├── test_lambda_function.py
    └── test_shopwired_client.py
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SHOPWIRED_API_KEY` | ✅ | Shopwired REST API key (used for HTTP Basic Auth) |
| `SHOPWIRED_WEBHOOK_SECRET` | ⬜ | If set, incoming requests are verified using the `X-ShopWired-Signature` HMAC header. Required to respond to the initial webhook verification request. |

## Local development with Docker Compose + ngrok

This is the recommended way to test webhook delivery end-to-end on your
local machine.

### 1 – Create your `.env` file

```bash
cp .env.example .env
# Edit .env and fill in SHOPWIRED_API_KEY (and optionally SHOPWIRED_WEBHOOK_SECRET)
```

### 2 – Start the container

```bash
docker compose up --build
```

This builds the image and starts `local_server.py`, a thin HTTP adapter that
forwards raw POST requests to the Lambda handler.  The service listens on
**port 8080**.

### 3 – Expose the port with ngrok

```bash
ngrok http 8080
```

ngrok prints a public HTTPS URL such as `https://abc123.ngrok-free.app`.

### 4 – Register the ngrok URL in Shopwired

Go to **Shopwired admin → Settings → Webhooks**, add a new webhook, and paste
the ngrok URL as the endpoint.  Shopwired will immediately send a verification
request; `local_server.py` handles it automatically.

### 5 – Watch logs

```bash
docker compose logs -f
```

### Without Docker (Python only)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in values
source .env            # or: export SHOPWIRED_API_KEY=...
python3 local_server.py
```

---

## Deploying with Serverless Stack (SST)

[SST](https://sst.dev) deploys the container to AWS Lambda with a public
Function URL – no API Gateway required.

### Prerequisites

- Node.js ≥ 18 and Docker (for building the container image locally)
- AWS credentials configured (`aws configure` or environment variables)

### First-time setup

```bash
npm install
npx sst bootstrap   # one-time per AWS account/region
```

### Deploy

```bash
export SHOPWIRED_API_KEY=your_api_key
export SHOPWIRED_WEBHOOK_SECRET=your_secret   # optional

npx sst deploy --stage dev
```

SST prints the `webhookUrl` at the end.  Paste that URL into Shopwired.

### Remove

```bash
npx sst remove --stage dev
```

---

## Building and running with Docker (manual)

```bash
# Build the container image
docker build -t shopwired-webhook .

# Run locally using the Lambda Runtime Interface Emulator (invocation format)
docker run -p 9000:8080 \
  -e SHOPWIRED_API_KEY=your_api_key \
  shopwired-webhook

# Test the RIE endpoint with curl
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "body": "{\"timestamp\":\"Tue, 23 Oct 2018 12:08:23 +0000\",\"event\":{\"id\":1,\"topic\":\"order.finalized\",\"subjectId\":42,\"data\":{\"object\":{\"id\":42,\"items\":[{\"product_id\":1,\"quantity\":2}]}}}}"
  }'
```

To deploy to AWS without SST, push the image to Amazon ECR and create (or update) a Lambda function pointing at the image.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Webhook payload

The handler expects the request body to match the Shopwired webhook spec. A normal event looks like:

```json
{
  "timestamp": "Tue, 23 Oct 2018 12:08:23 +0000",
  "event": {
    "id": 1,
    "businessId": 1,
    "createdAt": "Tue, 23 Oct 2018 12:08:23 +0000",
    "topic": "order.finalized",
    "subjectType": "order",
    "subjectId": 123,
    "data": {
      "object": {
        "id": 123,
        "items": [
          { "product_id": 456, "quantity": 2 },
          { "product_id": 789, "quantity": 1 }
        ]
      }
    }
  }
}
```

The initial verification request (sent by Shopwired when the webhook is first registered) looks like:

```json
{
  "timestamp": "Tue, 23 Oct 2018 12:08:23 +0000",
  "verificationToken": "some-token"
}
```

The handler responds with `HMAC-SHA256(verificationToken, webhookSecret)` as a plain-text body.

Any event topic other than `order.finalized` is acknowledged with a 200 and ignored.

## Response codes

| Status | Meaning |
|---|---|
| 200 | All items processed successfully (or event ignored) |
| 207 | Partial success – some items failed (see `errors` array in response body) |
| 400 | Bad request (unparseable body) |
| 401 | Signature verification failed |
| 500 | Server-side configuration error (e.g. missing API key) |