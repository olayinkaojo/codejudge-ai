const uuid =
  "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
export function allowed(path: string, method: string) {
  return method === "GET"
    ? ["tasks", "reviews", "reviews/config"].includes(path) ||
        new RegExp(`^(tasks|evaluations|reviews)/${uuid}$`).test(path)
    : method === "POST" && ["tasks", "evaluations", "reviews"].includes(path);
}
