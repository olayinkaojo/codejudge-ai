import { EvaluationDetails } from "@/components/evaluation";
import { Workspace } from "@/components/workspace";
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ history?: string }>;
}) {
  const { id } = await params;
  const query = await searchParams;
  return (
    <Workspace>
      <EvaluationDetails
        key={id}
        id={id}
        historyUnavailable={query.history === "unavailable"}
      />
    </Workspace>
  );
}
