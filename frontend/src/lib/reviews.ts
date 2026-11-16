export interface ReviewConfig {
  provider: "mock" | "openai";
  external: boolean;
  available: boolean;
  source_max_bytes: number;
  source_max_chars: number;
  retention_days: number;
  user_daily_limit: number;
}
export interface ReviewResult {
  summary: string;
  findings: {
    severity: "info" | "warning" | "critical";
    title: string;
    line: number | null;
    evidence: "text_pattern" | "speculative";
    explanation: string;
    suggestion: string;
    snippet: string | null;
  }[];
  positives: string[];
  limitations: string[];
}
export interface CodeReview {
  id: string;
  task_id: string | null;
  provider: "mock" | "openai";
  status: "processing" | "completed" | "failed";
  result: ReviewResult | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  expires_at: string;
}
export function reviewError(code: string | null) {
  const messages: Record<string, string> = {
    request_interrupted:
      "The request was interrupted. No automatic retry was made; an external request may have incurred cost.",
    provider_not_configured: "The external provider is not configured.",
    provider_unavailable:
      "The external provider could not complete this review.",
    provider_response_limit:
      "The provider exceeded the response or time limit.",
    invalid_provider_response:
      "The provider returned a result that could not be validated.",
  };
  return (
    (code && messages[code]) ||
    "This review could not be completed. You can explicitly request a new review from the editor."
  );
}
