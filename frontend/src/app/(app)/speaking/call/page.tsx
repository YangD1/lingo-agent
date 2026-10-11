import { RealtimeCallPage } from "@/components/speaking/realtime-call";

export default async function SpeakingCallPage({ searchParams }: PageProps<"/speaking/call">) {
  const { scenario } = await searchParams;
  return <RealtimeCallPage scenarioId={typeof scenario === "string" && scenario ? scenario : null} />;
}
