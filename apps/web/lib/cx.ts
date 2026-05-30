/**
 * Tiny class-name joiner. Filters out falsy values so conditional classes
 * read cleanly at the call site:
 *
 *   cx(styles.bubble, isUser && styles.user, streaming && styles.streaming)
 */
export function cx(
  ...parts: Array<string | false | null | undefined>
): string {
  return parts.filter(Boolean).join(" ");
}
