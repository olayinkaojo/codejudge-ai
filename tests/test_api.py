from fastapi.testclient import TestClient
from app.main import app, tasks, evaluations

client = TestClient(app)

def setup_function():
    tasks.clear()
    evaluations.clear()

def test_health():
    assert client.get("/health").json() == {"status": "ok"}

def test_task_and_evaluation():
    task = client.post("/tasks", json={"title": "Two Sum", "description": "Return indices of two values summing to target."})
    assert task.status_code == 201
    task_id = task.json()["id"]
    assert client.get(f"/tasks/{task_id}").status_code == 200
    result = client.post("/evaluations", json={"task_id": task_id, "submission_reference": "example-1", "tests_passed": 3, "tests_total": 4})
    assert result.status_code == 201
    assert result.json()["score"] == 75.0
    assert result.json()["verified"] is False
    assert client.get(f"/evaluations/{result.json()['id']}").status_code == 200

def test_invalid_evaluation():
    task_id = client.post("/tasks", json={"title": "Two Sum", "description": "Return indices of two values summing to target."}).json()["id"]
    result = client.post("/evaluations", json={"task_id": task_id, "submission_reference": "example-1", "tests_passed": 5, "tests_total": 4})
    assert result.status_code == 422

def test_missing_task():
    assert client.get("/tasks/not-found").status_code == 404
