import { notFound } from "next/navigation";

import { SpeakingSessionPage } from "@/components/speaking/speaking-session";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function SpeakingPracticePage({
  params,
  searchParams,
}: PageProps<"/speaking/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  // How a realtime call ended, from the call page that just closed (task 62.5).
  const { call_end: callEnd } = await searchParams;
  return <SpeakingSessionPage id={id} callEnd={typeof callEnd === "string" ? callEnd : null} />;
}
