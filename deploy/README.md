# Deploying to AWS Lambda

The app runs on Lambda behind a Function URL, using the
[AWS Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) so `app.py`
stays an ordinary Flask/WSGI app — no Lambda-specific code anywhere in it.

## Once

1. Start Docker.
2. An IAM principal that can use ECR, IAM (create role / put role policy) and Lambda:
   ```bash
   aws configure --profile mimir-deploy
   ```
   This is **not** the `mimir-bedrock` key — that one is deliberately
   `bedrock:InvokeModel`-only and cannot create infrastructure.
3. `cp deploy/.env.deploy.example deploy/.env.deploy` and fill in `COCKROACH_URL` and
   `COCKROACH_CA_PEM`. The file is gitignored.

## Every time

```bash
AWS_PROFILE=mimir-deploy bash deploy/deploy.sh
```

Idempotent — re-running rebuilds the image and updates the function in place, then prints
the Function URL and the status of `/healthz`, `/` and `/tutorial`.

## Why the function holds no AWS keys

Bedrock access comes from the execution role (`mimir-lambda-role`), scoped to exactly
`amazon.titan-embed-text-v2:0` and `amazon.nova-micro-v1:0` (plus the `us.` geo-profile
variant, which `_converse` falls back to for models that require an inference profile).
So there is no long-lived access key to store: the credential is a short-lived STS one that
Lambda injects and rotates.

## Region

`us-east-1` by default, matching the CockroachDB cluster. Co-location is not cosmetic:
moving the app into the cluster's region took 8 concurrent decisions from 13.5s to 1.5s.
