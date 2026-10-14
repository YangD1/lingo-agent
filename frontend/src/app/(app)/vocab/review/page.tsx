import { redirect } from "next/navigation";

/**
 * Flashcards are an overlay now (ADR 0038): links in the app open it in place, and this
 * address, opened directly (a bookmark, a new tab), lands on vocabulary with it open.
 */
export default async function ReviewPage({ searchParams }: PageProps<"/vocab/review">) {
  const { mode } = await searchParams;
  redirect(`/vocab?review=${mode === "new" ? "new" : "all"}`);
}
