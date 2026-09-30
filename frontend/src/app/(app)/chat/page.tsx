import { ChatApp } from "@/components/chat/chat-app";

export default async function ChatPage({ searchParams }: PageProps<"/chat">) {
  const { c, practice } = await searchParams;
  return (
    <ChatApp
      initialId={typeof c === "string" ? c : null}
      practiceKc={typeof practice === "string" ? practice : null}
    />
  );
}
