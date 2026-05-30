// Parses Server-Sent Events from a streaming `fetch` response.
// Yields each `data:` payload as a parsed JSON object.

export interface SSEFrame {
  type: "start" | "delta" | "done" | "cancelled" | "error";
  [k: string]: unknown;
}

export async function* parseSSE(
  res: Response,
  signal: AbortSignal,
): AsyncGenerator<SSEFrame> {
  if (!res.body) throw new Error("response has no body");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // SSE frames are separated by blank lines.
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        for (const line of raw.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const json = line.slice(5).trim();
          if (!json) continue;
          try {
            yield JSON.parse(json) as SSEFrame;
          } catch {
            // ignore malformed lines
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
