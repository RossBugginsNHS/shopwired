/// <reference path="./.sst/platform/config.d.ts" />

/**
 * SST (Serverless Stack) v3 configuration.
 *
 * Deploys the shopwired webhook handler as a container-based AWS Lambda
 * function with a Function URL (no API Gateway required).
 *
 * Prerequisites
 * -------------
 * 1. Install Node dependencies:
 *      npm install
 *
 * 2. Bootstrap SST in your AWS account (one-time per region):
 *      npx sst bootstrap
 *
 * 3. Configure credentials.  SST reads the same environment variables as
 *    the AWS CLI (AWS_PROFILE, AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY,
 *    or an assumed role).
 *
 * Deploy / remove
 * ---------------
 *   npx sst deploy --stage dev        # deploy to a dev stage
 *   npx sst deploy --stage production # deploy to production
 *   npx sst remove  --stage dev       # tear down dev stage
 *
 * The SHOPWIRED_API_KEY and SHOPWIRED_WEBHOOK_SECRET values are read from the
 * environment at deploy time.  Export them before running sst deploy, or load
 * them from a .env file with a tool such as `dotenv-cli`:
 *
 *   export SHOPWIRED_API_KEY=...
 *   export SHOPWIRED_WEBHOOK_SECRET=...
 *   npx sst deploy --stage dev
 */
export default $config({
  app(input) {
    return {
      name: "shopwired",
      // Keep resources when removing production; other stages are destroyed.
      removal: input?.stage === "production" ? "retain" : "remove",
      home: "aws",
    };
  },

  async run() {
    const apiKey = process.env.SHOPWIRED_API_KEY;
    if (!apiKey) {
      throw new Error(
        "SHOPWIRED_API_KEY environment variable must be set before deploying."
      );
    }

    const fn = new sst.aws.Function("ShopwiredWebhook", {
      // Build the container image from the project Dockerfile.
      image: {
        context: ".",
      },
      environment: {
        SHOPWIRED_API_KEY: apiKey,
        SHOPWIRED_WEBHOOK_SECRET: process.env.SHOPWIRED_WEBHOOK_SECRET ?? "",
      },
      // Expose a public HTTPS Function URL – paste this into the Shopwired
      // webhook settings as your endpoint URL.
      url: true,
      // Shopwired requires a response within 5 s; allow a small buffer.
      timeout: "10 seconds",
    });

    return {
      // Printed after every deploy.  Copy this URL into Shopwired.
      webhookUrl: fn.url,
    };
  },
});
