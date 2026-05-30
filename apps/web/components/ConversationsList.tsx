"use client";

import Link from "next/link";
import { useState } from "react";

import { API_BASE, Conversation } from "@/lib/api";
import { cx } from "@/lib/cx";
import styles from "./ConversationsList.module.css";

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

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

  return (
    <section className={styles.page}>
      <header className={styles.head}>
        <div>
          <h1 className={styles.title}>Conversations</h1>
          <p className={styles.subtitle}>
            {items.length} {items.length === 1 ? "conversation" : "conversations"}
          </p>
        </div>
        <Link href="/" className={styles.newBtn}>
          <span className={styles.plus} aria-hidden>+</span>
          New chat
        </Link>
      </header>

      {items.length === 0 ? (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>No conversations yet</p>
          <p className={styles.emptySub}>
            Start chatting and your history will appear here.
          </p>
          <Link href="/" className={styles.newBtn}>
            <span className={styles.plus} aria-hidden>+</span>
            Start a chat
          </Link>
        </div>
      ) : (
        <ul className={styles.list}>
          {items.map((c) => (
            <li key={c.id} className={styles.card}>
              <Link href={`/conversations/${c.id}`} className={styles.cardLink}>
                <div className={styles.cardMain}>
                  <span className={styles.cardTitle}>
                    {c.title || <span className={styles.untitled}>Untitled</span>}
                  </span>
                  <span className={styles.meta}>
                    {c.message_count ?? 0} messages · {relativeTime(c.updated_at)}
                  </span>
                </div>
              </Link>

              <div className={styles.cardActions}>
                <StatusBadge status={c.status} />
                {c.status === "active" && (
                  <button
                    onClick={() => cancel(c.id)}
                    className={styles.cancelBtn}
                  >
                    Cancel
                  </button>
                )}
                <span className={styles.chevron} aria-hidden>›</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StatusBadge({ status }: { status: Conversation["status"] }) {
  const tone =
    status === "active"
      ? styles.badgeOk
      : status === "cancelled"
      ? styles.badgeErr
      : styles.badgeNeutral;
  return (
    <span className={cx(styles.badge, tone)}>
      <span className={styles.dot} aria-hidden />
      {status}
    </span>
  );
}
