FROM python:3.12-slim

# Ensure stdout/stderr are not buffered and bytecode files are not written
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install Node.js for the mcp CLI and Python dependencies
ARG NODE_VERSION=20
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Persist OAuth database and key files
VOLUME ["/app/data"]

# Start the server directly
CMD ["python", "server.py"]
