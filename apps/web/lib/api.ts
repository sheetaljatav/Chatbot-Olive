// Single source of truth for the chat-api base URL.
// In the browser we use NEXT_PUBLIC_CHAT_API_URL; on the server side (RSC),
// we use CHAT_API_URL (which inside docker points at the internal hostname).

export const API_BASE =
  typeof window === "undefined"
    ? process.env.CHAT_API_URL || "http://chat-api:8000"
    : process.env.NEXT_PUBLIC_CHAT_API_URL || "http://localhost:8000";

export type Role = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  sequence: number;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string | null;
  status: "active" | "cancelled" | "completed";
  created_at: string;
  updated_at: string;
  message_count?: number;
  messages?: ChatMessage[];
}

export async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const swrFetcher = <T>(path: string): Promise<T> => fetchJSON<T>(path);
