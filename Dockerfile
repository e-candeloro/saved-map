# SavedMap web app: browse, map, search and related items over a data folder.
# Syncing (browser logins) and processing (GPU) normally run on your own computer; see README → Docker.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /usr/local/bin/uv
ENV UV_SYSTEM_PYTHON=1 UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# The lockfile's versions, with PyTorch from the index for TORCH: cpu (default, about 4 GB smaller)
# or a CUDA build such as cu128 (compose.gpu.yaml sets it)
ARG TORCH=cpu
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o req.txt \
 && grep -vE '^(torch|torchvision|triton|nvidia-)' req.txt > req-cpu.txt \
 && uv pip install $(sed -n 's/^\(torch\|torchvision\)==\([^+ ]*\).*/\1==\2/p' req.txt) \
      --index-url https://download.pytorch.org/whl/${TORCH} \
 && uv pip install -r req-cpu.txt \
 && rm req.txt req-cpu.txt

COPY savedmap ./savedmap
RUN uv pip install --no-deps . \
 && useradd --uid 1000 --no-create-home --home-dir /tmp savedmap \
 && mkdir -p /data /cache && chown savedmap:savedmap /data /cache

# Data folder (savedmap.db, media/, thumbs/, layout.json) and the search models (downloaded on first start)
ENV SAVEDMAP_DATA=/data HF_HOME=/cache/huggingface HOME=/tmp
USER 1000:1000
EXPOSE 8770
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8770/')"
CMD ["savedmap", "serve", "--host", "0.0.0.0", "--port", "8770"]
