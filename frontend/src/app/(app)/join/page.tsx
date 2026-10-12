import { JoinApp } from "@/components/settings/join-app";

export default async function JoinPage({ searchParams }: PageProps<"/join">) {
  const { code } = await searchParams;
  return <JoinApp code={typeof code === "string" ? code : ""} />;
}
