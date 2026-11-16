from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
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
from app.catalog import suites
from app.db import get_db
from app.middleware import BodyLimitMiddleware
from app.models import Evaluation, Submission, Task, Token, User
from app.schemas import (
    Credentials,
    EvaluationCreate,
    EvaluationOut,
    SubmissionCreate,
    SubmissionOut,
    TaskCreate,
    TaskOut,
)

app = FastAPI(title="CodeJudge AI", version="1.0.0")
app.add_middleware(BodyLimitMiddleware)


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
        db.execute(text("SELECT 1 FROM users LIMIT 1"))
        db.execute(select(Task.suite_spec).limit(0))
        db.execute(select(Submission.id).limit(0))
        db.execute(select(Evaluation.case_results, Evaluation.available_at).limit(0))
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ready"}


@app.post("/auth/register", status_code=201)
def register(payload: Credentials, db: Session = Depends(get_db)):
    user = User(username=payload.username, password_hash=hash_password(payload.password.get_secret_value()))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username unavailable") from None
    return {"id": str(user.id), "username": user.username}


@app.post("/auth/token")
def login(payload: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    valid = verify_password(payload.password.get_secret_value(), user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    return issue_token(db, user)


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
def create_task(payload: TaskCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    suite = None
    if payload.test_suite_id:
        suite = suites().get(payload.test_suite_id)
        if suite is None:
            raise HTTPException(422, "Unknown test suite")
    task = Task(owner_id=user.id, suite_spec=suite.model_dump() if suite else None, **payload.model_dump())
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
    payload: EvaluationCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    task = owned(db, Task, payload.task_id, user)
    if not task.suite_spec:
        raise HTTPException(409, "This challenge has no configured test suite")
    try:
        reference = UUID(payload.submission_reference)
    except ValueError:
        raise HTTPException(404, "Submission not found") from None
    submission = owned(db, Submission, reference, user)
    if submission.task_id != task.id:
        raise HTTPException(422, "Submission belongs to another challenge")
    evaluation = Evaluation(owner_id=user.id, **payload.model_dump())
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation


@app.get("/evaluations/{evaluation_id}", response_model=EvaluationOut)
def get_evaluation(evaluation_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned(db, Evaluation, evaluation_id, user)


@app.get("/test-suites")
def list_test_suites(user: User = Depends(current_user)):
    return [
        {
            "id": suite.id,
            "title": suite.title,
            "description": suite.description,
            "test_count": len(suite.cases),
        }
        for suite in suites().values()
    ]


@app.post("/submissions", status_code=201, response_model=SubmissionOut)
def create_submission(
    payload: SubmissionCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    task = owned(db, Task, payload.task_id, user)
    if not task.suite_spec:
        raise HTTPException(409, "This challenge has no configured test suite")
    submission = Submission(owner_id=user.id, **payload.model_dump())
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission
