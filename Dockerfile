FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 10001 --create-home codejudge
COPY --chown=codejudge:codejudge alembic.ini ./
COPY --chown=codejudge:codejudge migrations ./migrations
COPY --chown=codejudge:codejudge app ./app
USER codejudge
EXPOSE 8000
CMD ["python", "-m", "app.start"]

FROM base AS development
USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY --chown=codejudge:codejudge pyproject.toml ./
COPY --chown=codejudge:codejudge tests ./tests
COPY --chown=codejudge:codejudge scripts/db_backup.py ./scripts/db_backup.py
USER codejudge

FROM base AS production
