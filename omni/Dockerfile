# Omni Radar V6.0 - Multi-stage build
# Base: python:3.12-slim

# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# 通过清华源高速安装 uv，避免大陆服务器拉取 ghcr.io 镜像超时
RUN pip install --no-cache-dir uv -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY pyproject.toml uv.lock ./

# 安装依赖
RUN uv sync --frozen --no-install-project \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

RUN uv sync --frozen \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple


# Stage 2: Runtime image
FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /app /app

ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["/app/.venv/bin/streamlit", "run", "streamlit_app/app.py"]
