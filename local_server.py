#!/usr/bin/env python3
"""Lightweight HTTP server that wraps the Lambda handler for local development.

The Lambda Runtime Interface Emulator (RIE) built into the AWS Lambda base
image expects a specific invocation payload format.  When using ngrok to
tunnel real Shopwired webhook requests, this server is a simpler alternative:
it accepts plain HTTP POST requests and forwards them to the Lambda handler
using the same event structure that API Gateway / Lambda Function URLs produce.

Usage (without Docker):
    pip install -r requirements.txt
    SHOPWIRED_API_KEY=... python3 local_server.py

Usage (with Docker Compose – recommended):
    docker compose up

Then expose the local port with ngrok:
    ngrok http 8080

The public ngrok URL is what you register as your Shopwired webhook endpoint.
"""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from lambda_function import handler as lambda_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8080))


class _WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""

        # Build a Lambda proxy-style event from the raw HTTP request so
        # lambda_function.handler can process it without modification.
        event = {
            "body": body,
            "headers": {k: v for k, v in self.headers.items()},
        }

        result = lambda_handler(event, None)

        status = result.get("statusCode", 200)
        response_body = result.get("body", "")
        response_headers = result.get("headers", {})

        self.send_response(status)
        for name, value in response_headers.items():
            # Sanitise header name and value to prevent HTTP response splitting.
            safe_name = str(name).replace("\r", "").replace("\n", "")
            safe_value = str(value).replace("\r", "").replace("\n", "")
            self.send_header(safe_name, safe_value)
        self.end_headers()

        if isinstance(response_body, str):
            self.wfile.write(response_body.encode("utf-8"))
        else:
            self.wfile.write(response_body)

    def log_message(self, fmt: str, *args: object) -> None:
        logger.info("[%s] %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    server = HTTPServer(("", PORT), _WebhookHandler)
    logger.info("Local webhook server listening on http://0.0.0.0:%d", PORT)
    logger.info("Expose with:  ngrok http %d", PORT)
    logger.info("Stop with:    Ctrl-C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
