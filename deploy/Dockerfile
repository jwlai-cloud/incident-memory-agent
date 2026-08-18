# Flask on Lambda via the AWS Lambda Web Adapter: the app stays an ordinary WSGI
# server and the adapter translates Function URL requests, so app.py needs no
# Lambda-specific code and the Vercel deployment keeps working unchanged.
FROM public.ecr.aws/lambda/python:3.13

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
ENV AWS_LWA_PORT=8080 AWS_LWA_READINESS_CHECK_PATH=/healthz

WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY app.py .
COPY scripts/ scripts/
COPY templates/ templates/
COPY docs/tutorial.html docs/tutorial.html

# 1 worker, 8 threads: the work is IO-bound (Bedrock + CockroachDB round trips) and
# Lambda gives one request per instance anyway unless the adapter is told otherwise.
ENTRYPOINT []
CMD ["gunicorn","--bind","0.0.0.0:8080","--workers","1","--threads","8","--timeout","300","app:app"]
