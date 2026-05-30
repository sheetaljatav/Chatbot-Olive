import ConversationsList from "@/components/ConversationsList";
import { Conversation, fetchJSON } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ConversationsPage() {
  let conversations: Conversation[] = [];
  try {
    conversations = await fetchJSON<Conversation[]>("/conversations");
  } catch (e) {
    return (
      <div className="page-error">
        Failed to load conversations: {(e as Error).message}
      </div>
    );
  }
  return <ConversationsList initial={conversations} />;
}
