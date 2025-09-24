# Multi-stage build for smaller final image
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements-prod.txt .
RUN pip install --no-cache-dir --user -r requirements-prod.txt

# Optionally install Playwright browsers (commented out for smaller size)
# RUN /root/.local/bin/playwright install --with-deps chromium

# Production stage
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install minimal runtime dependencies (if Playwright needed)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     libnss3 \
#     libatk-bridge2.0-0 \
#     libdrm2 \
#     libxkbcommon0 \
#     libgtk-3-0 \
#     libgbm1 \
#     libasound2 \
#     && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY . .

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Run FastAPI with uvicorn
CMD ["python", "start_api.py", "--prod", "--host", "0.0.0.0", "--port", "8004"]