"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cx } from "@/lib/cx";
import styles from "./Header.module.css";

const NAV = [
  { href: "/", label: "Chat" },
  { href: "/conversations", label: "Conversations" },
  { href: "/dashboard", label: "Dashboard" },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/" || pathname.startsWith("/conversations/");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function Header() {
  const pathname = usePathname() || "/";

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          <span className={styles.logo} aria-hidden />
          <span className={styles.brandText}>Lumen</span>
          <span className={styles.brandSub}>chat</span>
        </Link>

        <nav className={styles.nav}>
          {NAV.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cx(styles.link, active && styles.linkActive)}
                aria-current={active ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
