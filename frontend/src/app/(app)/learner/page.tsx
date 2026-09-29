import { LearnerApp } from "@/components/learner/learner-app";

export default async function LearnerPage({ searchParams }: PageProps<"/learner">) {
  const { kc } = await searchParams;
  return <LearnerApp focusKc={typeof kc === "string" ? kc : null} />;
}
