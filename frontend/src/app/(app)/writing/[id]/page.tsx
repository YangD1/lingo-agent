import { notFound } from "next/navigation";

import { WritingReview } from "@/components/writing/writing-review";

export default async function WritingReviewPage({ params }: PageProps<"/writing/[id]">) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return <WritingReview id={Number(id)} />;
}
