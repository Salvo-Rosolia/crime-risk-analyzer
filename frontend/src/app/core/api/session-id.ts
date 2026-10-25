/** Intestazione con cui il backend riconosce la sessione delle fonti (`SESSION_HEADER`). */
export const SESSION_HEADER = 'X-Session-Id';

const STORAGE_KEY = 'cra.session-id';

/** Il backend accetta 16-128 caratteri `[A-Za-z0-9_-]`: un UUID senza trattini ne ha 32. */
function newSessionId(): string {
  return crypto.randomUUID().replaceAll('-', '');
}

/**
 * Token di sessione scelto dal client: lo stesso per tutta la scheda (sessionStorage), così un
 * ricaricamento ritrova le fonti caricate e non ne crea di orfane sul server. Se lo storage non è
 * disponibile ne vale uno per la sola vita della pagina.
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
