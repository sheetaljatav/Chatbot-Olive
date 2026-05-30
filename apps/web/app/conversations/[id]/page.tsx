import { notFound } from "next/navigation";

import Chat from "@/components/Chat";
import { Conversation, fetchJSON } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ResumeConversationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let conv: Conversation;
  try {
    conv = await fetchJSON<Conversation>(`/conversations/${id}`);
  } catch {
    notFound();
  }
  return <Chat conversationId={conv.id} initialMessages={conv.messages || []} />;
}
