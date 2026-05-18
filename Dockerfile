# syntax=docker/dockerfile:1
FROM public.ecr.aws/lambda/python:3.12

# Install runtime dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY lambda_function.py shopwired_client.py ./

# Lambda handler: <module>.<function>
CMD ["lambda_function.handler"]
