import { notFound } from "next/navigation";

import { SpeakingSessionPage } from "@/components/speaking/speaking-session";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function SpeakingPracticePage({ params }: PageProps<"/speaking/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  return <SpeakingSessionPage id={id} />;
}
