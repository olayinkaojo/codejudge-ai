FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 10001 --create-home codejudge
COPY --chown=codejudge:codejudge alembic.ini ./
COPY --chown=codejudge:codejudge migrations ./migrations
COPY --chown=codejudge:codejudge app ./app
COPY --chown=codejudge:codejudge contracts ./contracts
COPY --chown=codejudge:codejudge catalog ./catalog
USER codejudge
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]

FROM base AS development
USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY --chown=codejudge:codejudge pyproject.toml ./
COPY --chown=codejudge:codejudge tests ./tests
COPY --chown=codejudge:codejudge runner ./runner
USER codejudge

FROM base AS production
