# CodeJudge AI

A Python FastAPI backend prototype for evaluating coding-task submissions using transparent, test-count-based scoring.

## Features
- Create and retrieve coding tasks
- Record caller-reported test outcomes and calculate deterministic scores
- Retrieve evaluation reports
- Interactive OpenAPI documentation at `/docs`
- Pytest API tests and GitHub Actions CI

**Security note:** This prototype does not execute submitted code. Test outcomes are supplied by the caller and are explicitly marked unverified. Do not use it to assess untrusted submissions as if the results were independently validated.

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest -q
```

Visit http://127.0.0.1:8000/docs.

## Roadmap
- PostgreSQL persistence and database migrations
- Authentication and authorization
- Sandboxed execution worker with strict resource limits
- Verified test outcomes and richer evaluation rubrics
- Observability and deployment

This is an initial learning project, not a production-grade code judge or LLM evaluator.
