from uuid import uuid4
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="CodeJudge AI", version="0.1.0")
tasks: dict[str, dict] = {}
evaluations: dict[str, dict] = {}

class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=10)
    max_score: int = Field(default=100, ge=1, le=1000)

class EvaluationCreate(BaseModel):
    task_id: str
    submission_reference: str = Field(min_length=1)
    tests_passed: int = Field(ge=0)
    tests_total: int = Field(gt=0)
    feedback: str = ""

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/tasks", status_code=201)
def create_task(payload: TaskCreate):
    task_id = str(uuid4())
    task = {"id": task_id, **payload.model_dump()}
    tasks[task_id] = task
    return task

@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks[task_id]

@app.post("/evaluations", status_code=201)
def create_evaluation(payload: EvaluationCreate):
    task = tasks.get(payload.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if payload.tests_passed > payload.tests_total:
        raise HTTPException(status_code=422, detail="tests_passed cannot exceed tests_total")
    score = round(task["max_score"] * payload.tests_passed / payload.tests_total, 2)
    evaluation_id = str(uuid4())
    evaluation = {"id": evaluation_id, **payload.model_dump(), "score": score, "verified": False}
    evaluations[evaluation_id] = evaluation
    return evaluation

@app.get("/evaluations/{evaluation_id}")
def get_evaluation(evaluation_id: str):
    if evaluation_id not in evaluations:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return evaluations[evaluation_id]
