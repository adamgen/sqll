# The CI image: Python 3.13, uv, git, the pinned tools, and the harness
# dependencies. Build it from the repository root:
#   docker build -f ci/Dockerfile .
# ci/image_tag.py hashes all inputs of this file. CI pushes the image as
# ghcr.io/adamgen/sqll-ci:<hash>.
#
# The base images are pinned by digest. mirror.gcr.io is a Google cache of
# Docker Hub with the same digests. Set PYTHON_IMAGE or RUST_IMAGE only to
# use another copy of the same images. The apt steps install only what the
# base image does not have, so a local base with gcc and git needs no apt.
ARG PYTHON_IMAGE=mirror.gcr.io/library/python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
ARG RUST_IMAGE=mirror.gcr.io/library/rust:1.97.0-slim-trixie@sha256:686a437ead83701e8f871e66e838c3ec55f46b5fc235b025756396ac823bdc51

FROM ${RUST_IMAGE} AS rust

FROM ${PYTHON_IMAGE} AS base
COPY ci/uv-requirements.txt /tmp/uv-requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --require-hashes \
        --no-deps -r /tmp/uv-requirements.txt \
    && rm /tmp/uv-requirements.txt \
    && uv --version
ENV SQLL_TOOLS_DIR=/opt/sqll/tools \
    UV_PYTHON=/usr/local/bin/python3.13 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# sqruff with the "parser" and "python" features. The binary links to the
# libpython of this base image, so it builds on the same base.
FROM base AS sqruff
COPY --from=rust /usr/local/rustup /usr/local/rustup
COPY --from=rust /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN command -v gcc > /dev/null || { \
        apt-get update \
        && apt-get install -y --no-install-recommends gcc libc6-dev \
        && rm -rf /var/lib/apt/lists/*; }
COPY tools/sqruff/ /src/tools/sqruff/
RUN PYO3_PYTHON=/usr/local/bin/python3.13 \
    /src/tools/sqruff/install.sh /opt/sqll/tools/sqruff

FROM base
LABEL org.opencontainers.image.source=https://github.com/adamgen/sqll \
      org.opencontainers.image.description="sqll CI: Python 3.13, uv, sqlfluff, sqlfluff[rs], sqruff"
# git: actions/checkout needs it for submodules, and the harness reads the
# sqlfluff commit with it.
RUN command -v git > /dev/null || { \
        apt-get update \
        && apt-get install -y --no-install-recommends git \
        && rm -rf /var/lib/apt/lists/*; }
COPY --from=sqruff /opt/sqll/tools/sqruff /opt/sqll/tools/sqruff
COPY scripts/setup /src/scripts/setup
COPY tools/ /src/tools/
COPY harness/pyproject.toml harness/uv.lock /src/harness/
# scripts/setup installs the Python tools. It keeps the sqruff binary from
# the build stage because its version and features are correct.
ENV UV_PROJECT_ENVIRONMENT=/opt/sqll/harness-venv
RUN /src/scripts/setup \
    && uv sync --frozen --no-install-project --project /src/harness \
    && rm -rf /src /root/.cache/uv
