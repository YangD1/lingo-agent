import { JoinApp } from "@/components/settings/join-app";
import { getMe } from "@/lib/server-me";
import { SETUP_PATH } from "@/lib/setup";

export default async function JoinPage({ searchParams }: PageProps<"/join">) {
  const { code } = await searchParams;
  const me = await getMe();
  // Joined before finishing setup: the guide's model step now shows the main account's models.
  const next = me.user.setup_completed_at ? "/settings#membership" : `${SETUP_PATH}?step=model`;
  return <JoinApp code={typeof code === "string" ? code : ""} next={next} />;
}
