FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 yacb

COPY pyproject.toml README.md LICENSE /app/
COPY core /app/core
COPY skills /app/skills
COPY config.yaml /app/config.yaml

RUN pip install --upgrade pip && pip install -e .

RUN chown -R yacb:yacb /app

USER yacb

ENTRYPOINT ["yacb"]
CMD ["run", "config.yaml"]
