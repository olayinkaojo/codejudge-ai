"""Render Free-compatible startup. Migrations are explicit opt-in and run before Uvicorn."""

import logging
import os
import sys

from app.migrate import main as migrate


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    enabled = os.getenv("MIGRATE_ON_START", "false").lower()
    if enabled not in {"true", "false", "1", "0"}:
        logging.error("startup_configuration_error: MIGRATE_ON_START must be true or false")
        return 1
    try:
        port = int(os.getenv("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        logging.error("startup_configuration_error: PORT must be a valid port")
        return 1
    if enabled in {"true", "1"} and migrate() != 0:
        return 1
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--no-proxy-headers",
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
