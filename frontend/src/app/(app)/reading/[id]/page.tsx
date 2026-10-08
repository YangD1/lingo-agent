import { notFound } from "next/navigation";

import { ReadingArticle } from "@/components/reading/reading-article";

export default async function ReadingArticlePage({ params }: PageProps<"/reading/[id]">) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return <ReadingArticle id={Number(id)} />;
}
