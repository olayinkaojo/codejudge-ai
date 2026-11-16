import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ReviewAction,
  ReviewContent,
  ReviewHistory,
} from "@/components/reviews";
import type { CodeReview } from "@/lib/reviews";
import { api } from "@/lib/client";
import { allowed } from "@/lib/proxy-policy";
vi.mock("@/lib/client", () => ({ api: vi.fn(), backend: "/api/backend" }));
const review: CodeReview = {
  id: "123",
  task_id: null,
  provider: "mock",
  status: "completed",
  error: null,
  created_at: "2026-01-01",
  completed_at: "2026-01-01",
  expires_at: "2026-02-01",
  result: {
    summary: "Simulated review",
    findings: [
      {
        severity: "warning",
        title: "<img src=x onerror=alert(1)>",
        line: 1,
        evidence: "speculative",
        explanation: "<script>alert(1)</script>",
        suggestion: "Check your assumptions",
        snippet: "<svg onload=alert(1)>",
      },
    ],
    positives: ["Useful structure"],
    limitations: ["Unverified hypothesis"],
  },
};
beforeEach(() => vi.resetAllMocks());
describe("private advisory code reviews", () => {
  it("escapes all provider text and distinguishes uncertainty from execution", () => {
    const { container } = render(<ReviewContent review={review} />);
    expect(screen.getByText("Simulated · mock")).toBeVisible();
    expect(screen.getByText(/Code was not executed/)).toBeVisible();
    expect(screen.getByText("Line 1")).toBeVisible();
    expect(screen.getByText("Model hypothesis · unverified")).toBeVisible();
    expect(screen.getByText("<script>alert(1)</script>")).toBeVisible();
    expect(container.querySelector("script, img, svg[onload]")).toBeNull();
  });
  it("shows failure without invented findings or a score", () => {
    render(
      <ReviewContent
        review={{
          ...review,
          status: "failed",
          result: null,
          error: "request_interrupted",
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("No automatic retry");
    expect(screen.queryByText("Findings")).toBeNull();
  });
  it("requires disclosure and consent before external transmission", async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({
        provider: "openai",
        external: true,
        available: true,
        user_daily_limit: 20,
        retention_days: 30,
      })
      .mockResolvedValueOnce({ ...review, provider: "openai" });
    render(<ReviewAction taskId="task" source="print('x')" />);
    await screen.findByText(/complete editor contents will be sent to OpenAI/);
    expect(screen.getByRole("button", { name: "Review code" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Review code" }));
    await screen.findByText("External AI · OpenAI");
    expect(api).toHaveBeenLastCalledWith(
      "/api/backend/reviews",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          task_id: "task",
          source: "print('x')",
          language: "python",
          external_consent: true,
        }),
      }),
    );
  });
  it("does not retry a failed create and displays rate limit errors", async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({
        provider: "mock",
        external: false,
        available: true,
        user_daily_limit: 20,
        retention_days: 30,
      })
      .mockRejectedValueOnce(new Error("Review usage limit reached"));
    render(<ReviewAction taskId="task" source="pass" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Review usage limit reached",
    );
    await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
  it("uses server-persisted history and bounded pagination", async () => {
    vi.mocked(api).mockResolvedValue([]);
    render(<ReviewHistory />);
    expect(await screen.findByText("No reviews on this page")).toBeVisible();
    expect(api).toHaveBeenCalledWith("/api/backend/reviews?limit=20&offset=0");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });
  it("allows only implemented review routes", () => {
    expect(allowed("reviews", "POST")).toBe(true);
    expect(allowed("reviews", "GET")).toBe(true);
    expect(allowed("reviews/config", "GET")).toBe(true);
    expect(allowed("reviews/config", "POST")).toBe(false);
    expect(allowed("reviews/123/source", "GET")).toBe(false);
    expect(allowed("reviews", "DELETE")).toBe(false);
  });
});
