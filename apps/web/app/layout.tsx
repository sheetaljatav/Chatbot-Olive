import "./globals.css";
import Link from "next/link";
import type { ReactNode } from "react";

export const metadata = {
  title: "LLM Chat",
  description: "Lightweight LLM chatbot with inference logging",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen flex flex-col">
          <header className="border-b border-zinc-800 px-6 py-3 flex items-center gap-6">
            <Link href="/" className="font-semibold tracking-tight">LLM Chat</Link>
            <nav className="flex gap-4 text-sm text-zinc-400">
              <Link href="/" className="hover:text-white">Chat</Link>
              <Link href="/conversations" className="hover:text-white">Conversations</Link>
              <Link href="/dashboard" className="hover:text-white">Dashboard</Link>
            </nav>
          </header>
          <main className="flex-1 flex flex-col">{children}</main>
        </div>
      </body>
    </html>
  );
}
