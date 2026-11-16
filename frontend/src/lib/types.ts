export interface Task {
  id: string;
  title: string;
  description: string;
  max_score: number;
  test_suite_id: string | null;
  created_at: string;
}
export type EvaluationStatus = "queued" | "running" | "succeeded" | "failed";
export interface TestSuite {
  id: string;
  title: string;
  description: string;
  test_count: number;
}
export interface CaseResult {
  id: string;
  label: string;
  status: "passed" | "failed";
  reason: string | null;
  duration_ms: number;
}
export interface Evaluation {
  id: string;
  task_id: string;
  submission_reference: string;
  status: EvaluationStatus;
  tests_passed: number | null;
  tests_total: number | null;
  score: number | null;
  feedback: string | null;
  case_results?: CaseResult[] | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}
export interface HistoryEntry {
  id: string;
  taskId: string;
  title: string;
  createdAt: string;
}
export const stateLabels: Record<EvaluationStatus, string> = {
  queued: "In queue",
  running: "Evaluating",
  succeeded: "Completed",
  failed: "Failed",
};
export function errorMessage(error: string | null) {
  const messages: Record<string, string> = {
    sandbox_not_configured:
      "The external runner is not configured. Your code was not executed.",
    sandbox_unavailable:
      "The runner could not be reached after the allowed attempts.",
    sandbox_http_error: "The runner returned an error.",
    invalid_sandbox_result:
      "The runner returned a result that could not be accepted.",
    invalid_submission_or_suite:
      "This legacy submission or challenge is not compatible with the current runner. Create a new challenge with a test suite.",
    retry_limit_exceeded:
      "The evaluation could not finish within the allowed attempts.",
  };
  return (
    (error && messages[error]) ||
    "The evaluation could not be completed. No score was awarded."
  );
}
