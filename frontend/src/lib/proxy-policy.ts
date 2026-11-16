const uuid =
  "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
export function allowed(path: string, method: string) {
  return method === "GET"
    ? path === "tasks" || new RegExp(`^(tasks|evaluations)/${uuid}$`).test(path)
    : method === "POST" && ["tasks", "evaluations"].includes(path);
}
