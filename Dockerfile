FROM python:3.11-slim

WORKDIR /app

# 安裝系統相依（pdfplumber 需要）
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# 先複製 requirements 利用 Docker layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式碼
COPY dashboard.py data_fetcher.py ./

# Streamlit 設定：關閉 telemetry、headless 模式
RUN mkdir -p /root/.streamlit && \
    printf '[server]\nheadless = true\nport = 8501\naddress = "0.0.0.0"\n\n[browser]\ngatherUsageStats = false\n' \
    > /root/.streamlit/config.toml

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8501/_stcore/health').raise_for_status()"

ENTRYPOINT ["streamlit", "run", "dashboard.py"]
