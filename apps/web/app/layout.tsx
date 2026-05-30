import "./globals.css";
import "./styles/tokens.css";
import "./styles/base.css";
import type { ReactNode } from "react";

import Header from "@/components/Header";

export const metadata = {
  title: "Lumen Chat",
  description: "A premium LLM chat client with built-in inference observability.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <Header />
          <main className="app-main">{children}</main>
        </div>
      </body>
    </html>
  );
}
