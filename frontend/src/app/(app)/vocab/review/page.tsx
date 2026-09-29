import { ReviewApp } from "@/components/vocab/review-app";

export default async function ReviewPage({ searchParams }: PageProps<"/vocab/review">) {
  const { mode } = await searchParams;
  return <ReviewApp mode={mode === "new" ? "new" : "all"} />;
}
