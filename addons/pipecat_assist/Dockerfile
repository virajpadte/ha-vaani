ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

ARG BUILD_VERSION=0.1.0
ARG BUILD_ARCH=amd64
ARG LEGACY_AMD64_NUMPY=false

ENV PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# This image is built locally on first install/update (no pre-built image is published),
# so the stage banners below exist purely to give the Supervisor's live build log visible
# checkpoints instead of an unexplained wall of apt/pip output. See the README for why.
RUN echo "==> [1/4] Installing system packages (ffmpeg, audio libs, build tools)..."
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        ffmpeg \
        libffi-dev \
        libopus0 \
        libsndfile1 \
        libssl-dev \
        libvpx7 \
        python3 \
        python3-dev \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /tmp/pipecat_assist/pyproject.toml
COPY constraints-legacy-amd64.txt /tmp/pipecat_assist/constraints-legacy-amd64.txt
COPY app/ /tmp/pipecat_assist/app/
RUN echo "==> [2/4] Installing Python dependencies - this is the slow step (numpy, numba," \
    && echo "    onnxruntime, scipy, aiortc, opencv and friends). Several minutes is normal;" \
    && echo "    can run 15-20+ minutes on a Raspberry Pi or other ARM hardware."
RUN if [ "${LEGACY_AMD64_NUMPY}" = "true" ]; then \
        pip3 install --constraint /tmp/pipecat_assist/constraints-legacy-amd64.txt /tmp/pipecat_assist; \
    else \
        pip3 install /tmp/pipecat_assist; \
    fi \
    && rm -rf /tmp/pipecat_assist
RUN echo "==> [3/4] Python dependencies installed. Copying application..."

COPY app/ /app/
COPY root/ /
RUN chmod a+x /run.sh
RUN echo "==> [4/4] Build complete."

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Vaani" \
    org.opencontainers.image.source="https://github.com/virajpadte/ha-vaani"

WORKDIR /
CMD ["/run.sh"]
