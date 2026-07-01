FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (gcc for native extensions, ping for ICMP checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer-cache friendly)
COPY servicemonitor/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY servicemonitor/backend/ .

# Copy frontend (templates + static) alongside backend
COPY servicemonitor/frontend/ /frontend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
