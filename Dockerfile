# syntax=docker/dockerfile:1
FROM public.ecr.aws/lambda/python:3.12

# Install runtime dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source (local_server.py is used by docker-compose for local dev)
COPY lambda_function.py shopwired_client.py local_server.py ./

# Lambda handler: <module>.<function>
CMD ["lambda_function.handler"]
