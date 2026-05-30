"use client";

import Link from "next/link";
import { useState } from "react";

import { API_BASE, Conversation } from "@/lib/api";

export default function ConversationsList({
  initial,
}: {
  initial: Conversation[];
}) {
  const [items, setItems] = useState(initial);

  const cancel = async (id: string) => {
    try {
      await fetch(`${API_BASE}/conversations/${id}/cancel`, { method: "PUT" });
      setItems((prev) =>
        prev.map((c) => (c.id === id ? { ...c, status: "cancelled" } : c)),
      );
    } catch (e) {
      console.error(e);
    }
  };

  if (items.length === 0) {
    return <div className="text-zinc-500 text-sm">No conversations yet.</div>;
  }

  return (
    <ul className="space-y-2">
      {items.map((c) => (
        <li
          key={c.id}
          className="border border-zinc-800 rounded-xl p-3 hover:bg-zinc-900 flex justify-between items-center gap-3"
        >
          <Link
            href={`/conversations/${c.id}`}
            className="flex-1 min-w-0"
          >
            <div className="font-medium text-sm truncate">
              {c.title || <span className="text-zinc-500">untitled</span>}
            </div>
            <div className="text-xs text-zinc-500 mt-1">
              {c.message_count ?? 0} messages · updated{" "}
              {new Date(c.updated_at).toLocaleString()}
            </div>
          </Link>
          <span
            className={`text-xs px-2 py-1 rounded-full ${
              c.status === "active"
                ? "bg-emerald-900 text-emerald-300"
                : c.status === "cancelled"
                ? "bg-red-900 text-red-300"
                : "bg-zinc-800 text-zinc-400"
            }`}
          >
            {c.status}
          </span>
          {c.status === "active" && (
            <button
              onClick={() => cancel(c.id)}
              className="text-xs px-3 py-1 rounded-lg border border-red-900 text-red-300 hover:bg-red-950"
            >
              Cancel
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
