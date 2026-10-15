import { SetupApp } from "@/components/setup/setup-app";
import { getMe } from "@/lib/server-me";
import { initialView } from "@/lib/setup";

export default async function SetupPage({ searchParams }: PageProps<"/setup">) {
  const { step } = await searchParams;
  const me = await getMe();
  return <SetupApp user={me.user} initial={initialView(typeof step === "string" ? step : undefined)} />;
}
