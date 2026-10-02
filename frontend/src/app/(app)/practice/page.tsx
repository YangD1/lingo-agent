import { PracticeApp } from "@/components/practice/practice-app";
import type { Origin } from "@/lib/practice";

const ORIGINS: readonly Origin[] = ["dashboard", "learner", "card", "plan", "practice"];

export default async function PracticePage({ searchParams }: PageProps<"/practice">) {
  const { from, kc } = await searchParams;
  const origin = ORIGINS.find((o) => o === from) ?? null;
  return <PracticeApp from={origin} kc={origin && typeof kc === "string" ? kc : null} />;
}
