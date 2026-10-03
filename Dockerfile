# Raksha MCP server on AWS Lambda, as a plain ASGI web app behind Lambda Web Adapter.
FROM public.ecr.aws/docker/library/python:3.12-slim

# Lambda Web Adapter turns Function URL events into HTTP requests to port 8080
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY raksha_core ./raksha_core
COPY raksha_mcp ./raksha_mcp

ENV PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    RAKSHA_MODE=aws \
    RAKSHA_HOST=0.0.0.0 \
    RAKSHA_STATELESS=1 \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "uvicorn", "raksha_mcp.server:app", "--host", "0.0.0.0", "--port", "8080"]
