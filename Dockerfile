# syntax=docker/dockerfile:1
# check=skip=FromPlatformFlagConstDisallowed

FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.12.7 AS uv

FROM --platform=linux/amd64 python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/oracle/instantclient_23_26:/app/.venv/bin:${PATH}" \
    LD_LIBRARY_PATH="/opt/oracle/instantclient_23_26"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        unzip \
        libaio1 \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

ARG IC_VERSION=23.26.3.0.0
ARG IC_OTN_ID=2326300
RUN curl -fsSL -o /tmp/instantclient-basiclite.zip \
        "https://download.oracle.com/otn_software/linux/instantclient/${IC_OTN_ID}/instantclient-basiclite-linux.x64-${IC_VERSION}.zip" \
    && curl -fsSL -o /tmp/instantclient-tools.zip \
        "https://download.oracle.com/otn_software/linux/instantclient/${IC_OTN_ID}/instantclient-tools-linux.x64-${IC_VERSION}.zip" \
    && unzip -qo /tmp/instantclient-basiclite.zip -d /opt/oracle \
    && unzip -qo /tmp/instantclient-tools.zip -d /opt/oracle \
    && rm /tmp/instantclient-basiclite.zip /tmp/instantclient-tools.zip

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

ENTRYPOINT ["db_schema_extractor"]
