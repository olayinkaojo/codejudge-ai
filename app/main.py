from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import (
    DUMMY_HASH,
    bearer,
    current_user,
    hash_password,
    issue_token,
    token_digest,
    verify_password,
)
from app.auth_limits import admit
from app.auth_limits import logger as security_logger
from app.database_status import check_database, report_failure
from app.db import get_db
from app.idempotency import replay, resource_id
from app.middleware import BodyLimitMiddleware
from app.models import Evaluation, Task, Token, User
from app.reviews import router as review_router
from app.schemas import Credentials, EvaluationCreate, EvaluationOut, TaskCreate, TaskOut

app = FastAPI(title="CodeJudge AI", version="1.0.0")
app.add_middleware(BodyLimitMiddleware)


app.include_router(review_router)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    report_failure(exc, "database_request")
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Never echo rejected password/token or large submission values.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        },
    )


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        check_database(db)
    except Exception as exc:
        report_failure(exc, "readiness")
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ready"}


@app.post("/auth/register", status_code=201)
def register(payload: Credentials, request: Request, db: Session = Depends(get_db)):
    admit(db, request, payload.username, "register")
    user = User(username=payload.username, password_hash=hash_password(payload.password.get_secret_value()))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Same outward result for existing/new usernames; no account-ID enumeration.
        state = getattr(exc.orig, "sqlstate", None)
        if state != "23505" and getattr(exc.orig, "sqlite_errorcode", None) != 2067:
            raise
    security_logger.info("auth_registration_processed action=register")
    return {"detail": "Registration request processed. Continue to sign in."}


@app.post("/auth/token")
def login(payload: Credentials, request: Request, db: Session = Depends(get_db)):
    admit(db, request, payload.username, "login")
    user = db.scalar(select(User).where(User.username == payload.username))
    valid = verify_password(payload.password.get_secret_value(), user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        security_logger.warning("auth_credentials_rejected action=login")
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    result = issue_token(db, user)
    security_logger.info("auth_login_succeeded action=login")
    return result


@app.delete("/auth/token", status_code=204)
def logout(user: User = Depends(current_user), credentials=Depends(bearer), db: Session = Depends(get_db)):
    db.delete(db.get(Token, token_digest(credentials.credentials)))
    db.commit()
    return Response(status_code=204)


def owned(db, model, item_id, user):
    item = db.scalar(select(model).where(model.id == item_id, model.owner_id == user.id))
    if item is None:
        raise HTTPException(404, "Resource not found")
    return item


@app.post("/tasks", status_code=201, response_model=TaskOut)
def create_task(
    payload: TaskCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    request_id: UUID | None = Header(default=None, alias="Idempotency-Key"),
):
    existing = replay(db, Task, request_id, user.id, payload.model_dump())
    if existing is not None:
        return existing
    task = Task(owner_id=user.id, **resource_id(request_id), **payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(Task)
        .where(Task.owner_id == user.id)
        .order_by(Task.created_at, Task.id)
        .limit(limit)
        .offset(offset)
    ).all()


@app.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned(db, Task, task_id, user)


@app.post("/evaluations", status_code=202, response_model=EvaluationOut)
def create_evaluation(
    payload: EvaluationCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    request_id: UUID | None = Header(default=None, alias="Idempotency-Key"),
):
    owned(db, Task, payload.task_id, user)
    existing = replay(db, Evaluation, request_id, user.id, payload.model_dump())
    if existing is not None:
        return existing
    evaluation = Evaluation(owner_id=user.id, **resource_id(request_id), **payload.model_dump())
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation


@app.get("/evaluations/{evaluation_id}", response_model=EvaluationOut)
def get_evaluation(evaluation_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned(db, Evaluation, evaluation_id, user)
