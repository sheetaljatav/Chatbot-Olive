import ConversationsList from "@/components/ConversationsList";
import { Conversation, fetchJSON } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ConversationsPage() {
  let conversations: Conversation[] = [];
  try {
    conversations = await fetchJSON<Conversation[]>("/conversations");
  } catch (e) {
    return (
      <div className="p-6 text-sm text-red-400">
        Failed to load conversations: {(e as Error).message}
      </div>
    );
  }
  return (
    <div className="p-6">
      <h1 className="text-lg font-semibold mb-4">Conversations</h1>
      <ConversationsList initial={conversations} />
    </div>
  );
}
