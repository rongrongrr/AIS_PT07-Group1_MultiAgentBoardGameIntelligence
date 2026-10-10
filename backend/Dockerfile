# Backend: FastAPI + Playwright. The official Playwright image already contains Chromium and its
# system libraries; its tag must match the playwright version pinned in requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TILES_DB_PATH=/data/tiles.db \
    TILES_FORCE_HEADLESS=1     TILES_MLFLOW_URI=sqlite:////mlruns/mlflow.db

# CPU-only PyTorch (the default PyPI wheel on Linux bundles CUDA and is ~2 GB larger)
RUN pip install --break-system-packages --index-url https://download.pytorch.org/whl/cpu "torch==2.4.1"

COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

COPY . .
RUN mkdir -p /data /mlruns

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["uvicorn", "tiles.main:app", "--host", "0.0.0.0", "--port", "8000"]
