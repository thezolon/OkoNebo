FROM python:3.12-slim

LABEL org.opencontainers.image.title="OkoNebo" \
	org.opencontainers.image.description="Self-hosted weather dashboard with multi-provider fallback, responsive mobile UX, and operational observability" \
	org.opencontainers.image.authors="thezolon" \
	org.opencontainers.image.url="https://github.com/thezolon/OkoNebo" \
	org.opencontainers.image.documentation="https://github.com/thezolon/OkoNebo/blob/main/README.md" \
	org.opencontainers.image.source="https://github.com/thezolon/OkoNebo" \
	org.opencontainers.image.version="1.3.0"
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app/ app/
COPY scripts/ scripts/
COPY docs/ docs/
# Use example config as image default; docker-compose bind mount can override.
COPY config.yaml.example ./config.yaml

# Expose port for FastAPI backend
EXPOSE 8000

# Install curl for HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fs http://localhost:8000/api/bootstrap || exit 1

RUN useradd --no-create-home --shell /bin/false appuser && \
    chown -R appuser:appuser /app
USER appuser

# Run FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
