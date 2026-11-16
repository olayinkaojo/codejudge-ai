import { Challenge } from "@/components/challenge";
import { Workspace } from "@/components/workspace";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Workspace>
      <Challenge key={id} id={id} />
    </Workspace>
  );
}
