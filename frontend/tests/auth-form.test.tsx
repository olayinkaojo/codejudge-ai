import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AuthForm } from "@/components/auth-form";
import { api, ApiError } from "@/lib/client";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/client", () => ({
  api: vi.fn(),
  ApiError: class extends Error {
    constructor(
      message: string,
      public status: number,
    ) {
      super(message);
    }
  },
}));
it("explains expired sessions and allows accessible password visibility", () => {
  render(<AuthForm expired />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Your session has expired",
  );
  const password = screen.getByLabelText("Password", { exact: true });
  expect(password).toHaveAttribute("type", "password");
  fireEvent.click(screen.getByRole("button", { name: "Show password" }));
  expect(password).toHaveAttribute("type", "text");
});
it("focuses a meaningful registration error and prevents duplicate in-flight submits", async () => {
  let fail!: (e: Error) => void;
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((_, reject) => {
        fail = reject;
      }),
  );
  render(<AuthForm register />);
  fireEvent.change(screen.getByLabelText(/Username/), {
    target: { value: "alice" },
  });
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), {
    target: { value: "long-test-only-password" },
  });
  const form = screen
    .getByRole("button", { name: "Create account" })
    .closest("form")!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(api).toHaveBeenCalledTimes(1);
  fail(new ApiError("timeout", 503));
  const error = await screen.findByRole("alert");
  expect(error).toHaveTextContent("try signing in before registering again");
  expect(error.parentElement).toHaveFocus();
});
