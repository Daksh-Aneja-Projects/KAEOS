/**
 * Minimal Server-Sent Events reader for `fetch` responses.
 *
 * `EventSource` cannot be used here: it issues a bare GET with no way to attach
 * the Authorization header, and every streaming endpoint in this app is
 * authenticated. So we read the body ourselves.
 *
 * SSE frames are separated by a blank line and a single frame can be split
 * across network chunks, so partial frames are buffered and only complete ones
 * are parsed. Getting that wrong shows up as occasional dropped tokens under
 * load rather than as an obvious failure.
 */
export async function readEventStream(
  response: Response,
  onEvent: (event: any) => void,
): Promise<void> {
  if (!response.body) throw new Error('This response carried no stream to read.');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (!raw) continue;
        try {
          onEvent(JSON.parse(raw));
        } catch {
          // A frame that is not JSON is not worth aborting a live stream for.
        }
      }
    }
  }
}
