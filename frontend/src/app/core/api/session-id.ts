/** Header with which the backend recognizes the sources session (`SESSION_HEADER`). */
export const SESSION_HEADER = 'X-Session-Id';

const STORAGE_KEY = 'cra.session-id';

/**
 * The backend accepts 32-128 `[A-Za-z0-9_-]` characters, at least 10 of them distinct: a UUID
 * without dashes has exactly 32.
 */
function newSessionId(): string {
  return crypto.randomUUID().replaceAll('-', '');
}

/**
 * Session token chosen by the client: the same for the whole tab (sessionStorage), so a
 * reload finds the uploaded sources again and does not create orphans on the server. If storage is
 * not available, one lives for the page's lifetime only.
 */
let memoryId: string | null = null;

export function sessionId(): string {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
    const created = newSessionId();
    sessionStorage.setItem(STORAGE_KEY, created);
    return created;
  } catch {
    memoryId ??= newSessionId();
    return memoryId;
  }
}
