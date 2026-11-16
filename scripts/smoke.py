"""Exercise a local disposable Compose stack; creates a user, task and evaluation."""

import argparse
import secrets
import subprocess
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--restart-api", action="store_true", help="Restart the local Compose API to verify persistence"
    )
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, trust_env=False, timeout=5) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/docs").status_code == 200
        credentials = {"username": "smoke_" + secrets.token_hex(8), "password": secrets.token_urlsafe(24)}
        assert client.post("/auth/register", json=credentials).status_code == 201
        token = client.post("/auth/token", json=credentials)
        assert token.status_code == 200
        headers = {"Authorization": "Bearer " + token.json()["access_token"]}
        response = client.post(
            "/tasks",
            headers=headers,
            json={
                "title": "Smoke task",
                "test_suite_id": "sum-two-v1",
                "description": "Verify durable authenticated evaluation workflow.",
            },
        )
        assert response.status_code == 201
        task = response.json()
        submission = client.post(
            "/submissions",
            headers=headers,
            json={"task_id": task["id"], "source": "a,b=map(int,input().split()); print(a+b)"},
        )
        assert submission.status_code == 201
        response = client.post(
            "/evaluations",
            headers=headers,
            json={
                "task_id": task["id"],
                "submission_reference": submission.json()["id"],
            },
        )
        assert response.status_code == 202
        evaluation_id = response.json()["id"]
        for _ in range(30):
            response = client.get("/evaluations/" + evaluation_id, headers=headers)
            assert response.status_code == 200
            evaluation = response.json()
            if evaluation["status"] == "failed":
                break
            time.sleep(0.5)
        assert evaluation["status"] == "failed" and evaluation["error"] == "sandbox_not_configured"
        assert evaluation["score"] is None
        if args.restart_api:
            subprocess.run(["docker", "compose", "restart", "api"], check=True)
            for _ in range(30):
                try:
                    if client.get("/ready").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.5)
            assert client.get("/tasks/" + task["id"], headers=headers).json() == task
            assert client.get("/evaluations/" + evaluation_id, headers=headers).json() == evaluation
        assert client.delete("/auth/token", headers=headers).status_code == 204
        assert client.get("/tasks", headers=headers).status_code == 401
    print(
        "Smoke checks passed: authenticated API, durable queue, fail-closed worker, token revocation"
        + (", restart persistence." if args.restart_api else ".")
    )


if __name__ == "__main__":
    main()
