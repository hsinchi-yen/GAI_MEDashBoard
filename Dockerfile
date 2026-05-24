FROM python:3.11-slim

WORKDIR /app

# System dependencies (build-essential for compiled packages, curl for HEALTHCHECK)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies — cached as a separate layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY dashboard.py data_fetcher.py db_manager.py macro_index.py scheduler.py ./
COPY fetchers/ fetchers/

# Streamlit config: headless, port 8501, no telemetry
RUN mkdir -p /root/.streamlit && \
    printf '[server]\nheadless = true\nport = 8501\naddress = "0.0.0.0"\n\n[browser]\ngatherUsageStats = false\n' \
    > /root/.streamlit/config.toml

# Entrypoint: start background APScheduler daemon, then Streamlit as PID 1 child
RUN printf '#!/bin/sh\nset -e\necho "[entrypoint] Starting scheduler..."\npython scheduler.py &\necho "[entrypoint] Starting Streamlit..."\nexec streamlit run dashboard.py\n' \
    > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 8501

# Generous start-period for resource-constrained Yocto systems
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD curl -sf http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
