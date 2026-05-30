"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE, ChatMessage } from "@/lib/api";
import { parseSSE } from "@/lib/stream";
import { cx } from "@/lib/cx";
import styles from "./Chat.module.css";

interface Props {
  conversationId?: string;
  initialMessages?: ChatMessage[];
}

type UIMessage = {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  cancelled?: boolean;
  error?: string;
};

const SUGGESTIONS = [
  "Explain quantum entanglement simply",
  "Draft a polite follow-up email",
  "Give me a 5-minute stretching routine",
  "Compare REST and GraphQL",
];

/** Immutably replace the trailing assistant message. */
function patchLastAssistant(
  list: UIMessage[],
  patch: Partial<UIMessage>,
): UIMessage[] {
  const copy = list.slice();
  const last = copy[copy.length - 1];
  if (last && last.role === "assistant") {
    copy[copy.length - 1] = { ...last, ...patch };
  }
  return copy;
}

export default function Chat({ conversationId, initialMessages = [] }: Props) {
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

  const send = useCallback(
    async (override?: string) => {
      const text = (override ?? input).trim();
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
            setMessages((prev) =>
              patchLastAssistant(prev, {
                content: (prev[prev.length - 1]?.content ?? "") + delta,
              }),
            );
          } else if (frame.type === "done") {
            setMessages((prev) => patchLastAssistant(prev, { streaming: false }));
          } else if (frame.type === "cancelled") {
            setMessages((prev) =>
              patchLastAssistant(prev, { streaming: false, cancelled: true }),
            );
          } else if (frame.type === "error") {
            setMessages((prev) =>
              patchLastAssistant(prev, {
                streaming: false,
                error: String(frame.message),
              }),
            );
          }
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          // Stop aborts the connection client-side, so the server's
          // "cancelled" frame never arrives — mark it here.
          setMessages((prev) =>
            patchLastAssistant(prev, { streaming: false, cancelled: true }),
          );
        } else {
          setMessages((prev) =>
            patchLastAssistant(prev, {
              streaming: false,
              error: (err as Error).message,
            }),
          );
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [input, isStreaming, convId],
  );

  // Stop only aborts the in-flight generation; the conversation stays active.
  const stop = useCallback(() => abortRef.current?.abort(), []);

  const isEmpty = messages.length === 0;

  return (
    <div className={styles.root}>
      <div className={styles.scroll}>
        <div className={styles.thread}>
          {isEmpty ? (
            <div className={styles.empty}>
              <div className={styles.emptyGlow} aria-hidden />
              <h1 className={styles.emptyTitle}>How can I help today?</h1>
              <p className={styles.emptySub}>
                Ask anything — responses stream live and every call is logged to
                the dashboard.
              </p>
              <div className={styles.suggestions}>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    className={styles.chip}
                    onClick={() => send(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) => <Bubble key={i} message={m} />)
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className={styles.composerWrap}>
        <div className={styles.composer}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
            placeholder="Message Lumen…"
            className={styles.textarea}
          />
          {isStreaming ? (
            <button
              onClick={stop}
              className={cx(styles.action, styles.stop)}
              aria-label="Stop generating"
            >
              <span className={styles.stopIcon} aria-hidden />
              Stop
            </button>
          ) : (
            <button
              onClick={() => send()}
              disabled={!input.trim()}
              className={cx(styles.action, styles.sendBtn)}
              aria-label="Send message"
            >
              Send
              <SendIcon />
            </button>
          )}
        </div>
        <p className={styles.hint}>
          Press <kbd className={styles.kbd}>Enter</kbd> to send ·{" "}
          <kbd className={styles.kbd}>Shift</kbd>+
          <kbd className={styles.kbd}>Enter</kbd> for a new line
        </p>
      </div>
    </div>
  );
}

function Bubble({ message }: { message: UIMessage }) {
  const isUser = message.role === "user";
  const showTyping = message.streaming && !message.content;

  return (
    <div className={cx(styles.row, isUser ? styles.rowUser : styles.rowAssistant)}>
      {!isUser && (
        <div className={styles.avatar} aria-hidden>
          <span className={styles.avatarMark} />
        </div>
      )}
      <div
        className={cx(
          styles.bubble,
          isUser ? styles.user : styles.assistant,
          message.error && styles.errored,
        )}
      >
        {message.error ? (
          <span className={styles.errorText}>⚠ {message.error}</span>
        ) : showTyping ? (
          <span className={styles.typing} aria-label="Assistant is typing">
            <i />
            <i />
            <i />
          </span>
        ) : (
          <>
            <span className={styles.content}>{message.content}</span>
            {message.streaming && <span className={styles.caret} aria-hidden />}
          </>
        )}
        {message.cancelled && <span className={styles.cancelled}>cancelled</span>}
      </div>
    </div>
  );
}

function SendIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 12L20 4L13 20L11 13L4 12Z"
        fill="currentColor"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}
