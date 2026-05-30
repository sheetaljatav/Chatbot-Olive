"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { API_BASE, ChatMessage } from "@/lib/api";
import { parseSSE } from "@/lib/stream";

interface Props {
  conversationId?: string;
  initialMessages?: ChatMessage[];
}

type UIMessage = { role: "user" | "assistant"; content: string; streaming?: boolean };

export default function Chat({ conversationId, initialMessages = [] }: Props) {
  const router = useRouter();
  const [messages, setMessages] = useState<UIMessage[]>(() =>
    initialMessages.map((m) => ({
      role: m.role === "assistant" ? "assistant" : "user",
      content: m.content,
    })),
  );
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [convId, setConvId] = useState<string | undefined>(conversationId);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "", streaming: true },
    ]);
    setIsStreaming(true);

    const ctl = new AbortController();
    abortRef.current = ctl;

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: convId, message: text }),
        signal: ctl.signal,
      });
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);

      for await (const frame of parseSSE(res, ctl.signal)) {
        if (frame.type === "start" && !convId) {
          const id = String(frame.conversation_id);
          setConvId(id);
          // Reflect the new conversation id in the URL without a full nav.
          window.history.replaceState({}, "", `/conversations/${id}`);
        } else if (frame.type === "delta") {
          const delta = String(frame.text || "");
          setMessages((prev) => {
            const copy = prev.slice();
            const last = copy[copy.length - 1];
            if (last && last.role === "assistant") {
              copy[copy.length - 1] = { ...last, content: last.content + delta };
            }
            return copy;
          });
        } else if (frame.type === "done") {
          setMessages((prev) => {
            const copy = prev.slice();
            const last = copy[copy.length - 1];
            if (last) copy[copy.length - 1] = { ...last, streaming: false };
            return copy;
          });
        } else if (frame.type === "cancelled") {
          setMessages((prev) => {
            const copy = prev.slice();
            const last = copy[copy.length - 1];
            if (last) {
              copy[copy.length - 1] = {
                ...last,
                content: last.content + "\n\n_[cancelled]_",
                streaming: false,
              };
            }
            return copy;
          });
        } else if (frame.type === "error") {
          setMessages((prev) => {
            const copy = prev.slice();
            const last = copy[copy.length - 1];
            if (last) {
              copy[copy.length - 1] = {
                ...last,
                content: `_error: ${String(frame.message)}_`,
                streaming: false,
              };
            }
            return copy;
          });
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        // Stop button aborts the connection client-side, so the server's
        // "cancelled" SSE frame never arrives — render the marker here.
        setMessages((prev) => {
          const copy = prev.slice();
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant") {
            copy[copy.length - 1] = {
              ...last,
              content: last.content + "\n\n_[cancelled]_",
              streaming: false,
            };
          }
          return copy;
        });
      } else {
        console.error(err);
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [input, isStreaming, convId]);

  // Stop only aborts the in-flight generation. The conversation stays active
  // and can be continued. The explicit "Cancel conversation" action lives on
  // the conversations list page.
  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-zinc-500 text-sm">Start a conversation below.</div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`max-w-3xl whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm ${
              m.role === "user"
                ? "bg-zinc-800 ml-auto"
                : "bg-zinc-900 border border-zinc-800"
            }`}
          >
            {m.content || (m.streaming ? "…" : "")}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="border-t border-zinc-800 p-4 flex gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={2}
          placeholder="Type a message…"
          className="flex-1 resize-none rounded-xl bg-zinc-900 border border-zinc-800 px-3 py-2 text-sm focus:outline-none focus:border-zinc-600"
        />
        {isStreaming ? (
          <button
            onClick={stop}
            className="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-sm font-medium"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={send}
            disabled={!input.trim()}
            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-sm font-medium"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
