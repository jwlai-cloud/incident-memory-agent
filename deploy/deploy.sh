#!/usr/bin/env bash
# Build and deploy the app to AWS Lambda behind a Function URL.
#
#   AWS_PROFILE=mimir-deploy bash deploy/deploy.sh
#
# Idempotent: re-running updates the image and the function in place. Bedrock access
# comes from the execution role, so no AWS keys are stored in the function's env.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
NAME=mimir
ROLE=${NAME}-lambda-role
ACCT=$(aws sts get-caller-identity --query Account --output text)
REPO="${ACCT}.dkr.ecr.${REGION}.amazonaws.com/${NAME}"

say(){ printf '\n\033[1m== %s\033[0m\n' "$1"; }

say "ECR repository"
aws ecr describe-repositories --repository-names "$NAME" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$NAME" --region "$REGION" >/dev/null
# Without this, CreateFunction fails with a bare "Lambda does not have permission to
# access the ECR image". aws:SourceArn pins it to this one function rather than letting
# any Lambda in the account pull the image (confused-deputy). mktemp because a fixed
# /tmp path can be swapped between the write and the read.
ECRPOL=$(mktemp); trap 'rm -f "$ECRPOL" "${ENVFILE:-}"' EXIT
cat > "$ECRPOL" <<JSON
{"Version":"2012-10-17","Statement":[{"Sid":"LambdaECRImageRetrievalPolicy","Effect":"Allow",
 "Principal":{"Service":"lambda.amazonaws.com"},
 "Action":["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
 "Condition":{"StringEquals":{"aws:SourceArn":"arn:aws:lambda:${REGION}:${ACCT}:function:${NAME}"}}}]}
JSON
aws ecr set-repository-policy --repository-name "$NAME" --region "$REGION" \
  --policy-text "file://$ECRPOL" >/dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCT}.dkr.ecr.${REGION}.amazonaws.com"

say "Build + push (arm64)"
docker build --platform linux/arm64 -f deploy/Dockerfile -t "${REPO}:latest" .
docker push "${REPO}:latest"

say "Execution role"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "waiting for role to propagate..."; sleep 12
fi
# least privilege: exactly the two models the app calls, nothing else
aws iam put-role-policy --role-name "$ROLE" --policy-name bedrock-invoke-two-models \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"bedrock:InvokeModel\"],\"Resource\":[
    \"arn:aws:bedrock:${REGION}::foundation-model/amazon.titan-embed-text-v2:0\",
    \"arn:aws:bedrock:${REGION}::foundation-model/amazon.nova-micro-v1:0\",
    \"arn:aws:bedrock:${REGION}::foundation-model/us.amazon.nova-micro-v1:0\"]}]}"
ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)

say "Function"
# COCKROACH_URL / COCKROACH_CA_PEM / DEMO_PASSCODE come from deploy/.env.deploy,
# which is gitignored. Written to a temp JSON so secrets never appear in ps output.
ENVFILE=$(mktemp)
python3 - "$ENVFILE" <<'PY'
import json, os, sys, pathlib
env = {}
p = pathlib.Path("deploy/.env.deploy")
if p.exists():
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
# AWS_REGION is reserved by Lambda and cannot be set; the SDK picks it up anyway.
# All of these are reserved by Lambda and rejected if set. More to the point, the
# execution role is what grants Bedrock — a stray key or session token in .env.deploy
# would shadow it with something that expires or is over-scoped.
for reserved in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ACCESS_KEY", "AWS_ACCESS_KEY_ID",
                 "AWS_SECRET_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    env.pop(reserved, None)
json.dump({"Variables": env}, open(sys.argv[1], "w"))
print(f"  {len(env)} env var(s): {', '.join(sorted(env))}")
PY

if aws lambda get-function --function-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$NAME" --image-uri "${REPO}:latest" --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$NAME" --region "$REGION"
  aws lambda update-function-configuration --function-name "$NAME" --region "$REGION" \
    --timeout 300 --memory-size 1024 --environment "file://$ENVFILE" >/dev/null
else
  aws lambda create-function --function-name "$NAME" --region "$REGION" \
    --package-type Image --code "ImageUri=${REPO}:latest" --role "$ROLE_ARN" \
    --architectures arm64 --timeout 300 --memory-size 1024 \
    --environment "file://$ENVFILE" >/dev/null
fi
aws lambda wait function-updated --function-name "$NAME" --region "$REGION"

say "Function URL"
aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" >/dev/null 2>&1 || \
  aws lambda create-function-url-config --function-name "$NAME" --auth-type NONE --region "$REGION" >/dev/null
# Since Oct 2025 a public function URL needs BOTH statements, and the second takes
# --invoked-via-function-url rather than --function-url-auth-type. Missing either one 403s
# every path while AuthType is already NONE, which reads like a problem anywhere else.
# Reconciled on every run, not only at creation: a create-only version can never repair a
# function whose policy is already wrong. ResourceConflict just means it is already right.
add_url_perm() {
  aws lambda add-permission --function-name "$NAME" --statement-id "$1" --region "$REGION" \
    --action "$2" --principal '*' "${@:3}" >/dev/null 2>&1 \
    || echo "    $1 already present"
}
add_url_perm UrlPolicyInvokeURL      lambda:InvokeFunctionUrl --function-url-auth-type NONE
add_url_perm UrlPolicyInvokeFunction lambda:InvokeFunction    --invoked-via-function-url
URL=$(aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" --query FunctionUrl --output text)

say "Live at $URL"
# Retry briefly: the first request after a new image is a cold start on a 1GB arm64
# container. Then exit non-zero on anything that is not 200 — a deploy script that prints
# a 403 and exits 0 reports a broken deployment as a successful one.
fail=0
for path in healthz "" tutorial api/state; do
  code=000
  for attempt in 1 2 3 4 5; do
    code=$(curl -s -m 30 -o /dev/null -w '%{http_code}' "${URL}${path}") || code=000
    [ "$code" = "200" ] && break
    sleep 4
  done
  printf '  /%-10s %s\n' "$path" "$code"
  [ "$code" = "200" ] || fail=1
done
if [ "$fail" -ne 0 ]; then
  echo "  DEPLOY FAILED: at least one route did not return 200" >&2
  exit 1
fi
echo "  all routes 200"

