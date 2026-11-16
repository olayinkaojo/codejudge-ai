const uuid =
  "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
export function allowed(path: string, method: string) {
  return method === "GET"
    ? ["tasks", "test-suites"].includes(path) ||
        new RegExp(`^(tasks|evaluations)/${uuid}$`).test(path)
    : method === "POST" &&
        ["tasks", "evaluations", "submissions"].includes(path);
}
