import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { EvaluationDetails } from "@/components/evaluation";
const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/client", () => ({ api, backend: "/api/backend" }));
const result = {
  id: "evaluation-id",
  task_id: "task-id",
  submission_reference: "artifact-1",
  created_at: "2026-01-01",
  completed_at: null,
  score: null,
  tests_passed: null,
  tests_total: null,
  feedback: null,
  error: null,
};
beforeEach(() => {
  api.mockReset();
});
it("shows a genuine queued state without a score or invented test output", async () => {
  api.mockImplementation((path: string) =>
    Promise.resolve(
      path.includes("tasks")
        ? { title: "Two Sum", max_score: 100 }
        : { ...result, status: "queued" },
    ),
  );
  render(<EvaluationDetails id="evaluation-id" />);
  expect(
    await screen.findByText("Your submission is in the queue."),
  ).toBeInTheDocument();
  expect(screen.getByText("No score available")).toBeInTheDocument();
  expect(screen.getByText("No test results available")).toBeInTheDocument();
});
it("explains an unconfigured runner honestly", async () => {
  api.mockResolvedValue({
    ...result,
    status: "failed",
    error: "sandbox_not_configured",
  });
  render(<EvaluationDetails id="evaluation-id" />);
  expect(
    await screen.findByText(
      "The external runner is not configured. Your code was not executed.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText("points awarded")).not.toBeInTheDocument();
});
it("only renders scores and feedback supplied by a successful runner result", async () => {
  api.mockImplementation((path: string) =>
    Promise.resolve(
      path.includes("tasks")
        ? { title: "Two Sum", max_score: 100 }
        : {
            ...result,
            status: "succeeded",
            score: 75,
            tests_passed: 3,
            tests_total: 4,
            feedback: "<script>untrusted feedback</script>",
          },
    ),
  );
  render(<EvaluationDetails id="evaluation-id" />);
  expect(await screen.findByText("points awarded")).toBeInTheDocument();
  expect(
    screen.getByText("<script>untrusted feedback</script>"),
  ).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
});
it("stops and reports a polling failure instead of fabricating progress", async () => {
  api.mockRejectedValue(new Error("Connection unavailable"));
  render(<EvaluationDetails id="evaluation-id" />);
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Connection unavailable",
    ),
  );
  expect(screen.queryByText("points awarded")).not.toBeInTheDocument();
});
it("warns when browser history storage was unavailable", async () => {
  api.mockResolvedValue({
    ...result,
    status: "failed",
    error: "sandbox_not_configured",
  });
  render(<EvaluationDetails id="evaluation-id" historyUnavailable />);
  expect(
    screen.getByText(/This browser could not save the history entry/),
  ).toBeInTheDocument();
});
it("renders structured challenge cases without exposing raw or expected outputs", async () => {
  api.mockImplementation((path: string) =>
    Promise.resolve(
      path.includes("tasks")
        ? { title: "Two Sum", max_score: 100 }
        : {
            ...result,
            status: "succeeded",
            score: 50,
            tests_passed: 1,
            tests_total: 2,
            case_results: [
              {
                id: "normal",
                label: "Positive integers",
                status: "passed",
                reason: null,
                duration_ms: 22,
              },
              {
                id: "edge",
                label: "Large integers",
                status: "failed",
                reason: "time_limit",
                duration_ms: 1001,
              },
            ],
          },
    ),
  );
  render(<EvaluationDetails id="evaluation-id" />);
  expect(
    await screen.findByRole("region", { name: "Per-test results" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Large integers")).toBeInTheDocument();
  expect(screen.getByText("time limit")).toBeInTheDocument();
  expect(screen.getByText("1001 ms")).toBeInTheDocument();
});
it("does not assert isolated execution for a legacy aggregate result", async () => {
  api.mockResolvedValue({
    ...result,
    status: "succeeded",
    score: 75,
    tests_passed: 3,
    tests_total: 4,
    case_results: null,
  });
  render(<EvaluationDetails id="evaluation-id" />);
  expect(
    await screen.findByText(/Legacy aggregate result/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Per-test results" }),
  ).not.toBeInTheDocument();
});
