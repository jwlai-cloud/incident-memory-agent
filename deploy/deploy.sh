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
cat > /tmp/mimir-ecr-policy.json <<'JSON'
{"Version":"2012-10-17","Statement":[{"Sid":"LambdaECRImageRetrievalPolicy","Effect":"Allow",
 "Principal":{"Service":"lambda.amazonaws.com"},
 "Action":["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"]}]}
JSON
aws ecr set-repository-policy --repository-name "$NAME" --region "$REGION" \
  --policy-text file:///tmp/mimir-ecr-policy.json >/dev/null   # else CreateFunction: "Lambda does not have permission to access the ECR image"
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
ENVFILE=$(mktemp); trap 'rm -f "$ENVFILE"' EXIT
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
env.pop("AWS_REGION", None)
env.pop("AWS_ACCESS_KEY_ID", None)      # the execution role provides Bedrock access
env.pop("AWS_SECRET_ACCESS_KEY", None)
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
aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" >/dev/null 2>&1 || {
  aws lambda create-function-url-config --function-name "$NAME" --auth-type NONE --region "$REGION" >/dev/null
  # Since Oct 2025 a public function URL needs BOTH statements, and the second one takes
  # --invoked-via-function-url rather than --function-url-auth-type. Missing it yields a
  # 403 on every path with AuthType already NONE, which looks like a config problem
  # somewhere else entirely.
  aws lambda add-permission --function-name "$NAME" --statement-id UrlPolicyInvokeURL \
    --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE --region "$REGION" >/dev/null
  aws lambda add-permission --function-name "$NAME" --statement-id UrlPolicyInvokeFunction \
    --action lambda:InvokeFunction --principal '*' --invoked-via-function-url --region "$REGION" >/dev/null
}
URL=$(aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" --query FunctionUrl --output text)

say "Live at $URL"
for path in healthz "" tutorial; do
  printf '  /%-9s %s\n' "$path" "$(curl -s -o /dev/null -w '%{http_code}' "${URL}${path}")"
done
