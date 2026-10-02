import { WritingApp } from "@/components/writing/writing-app";

export default async function WritingPage({ searchParams }: PageProps<"/writing">) {
  const { again } = await searchParams;
  const id = typeof again === "string" && /^\d+$/.test(again) ? Number(again) : null;
  return <WritingApp again={id} />;
}
