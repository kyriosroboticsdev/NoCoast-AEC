// IFC files opened from disk, kept per session in IndexedDB. A session's own
// versions live on the backend and are re-fetched by url, but a file the user
// opened from the file system has nowhere else to go: localStorage is far too
// small for a model, so without this the session loses its model on restart.
// Every call degrades to a no-op (or null) when IndexedDB is unavailable.

const DB_NAME = "gbim";
const STORE = "files";
const DB_VERSION = 1;
/** Anything larger is left to the file system; the session then asks the user to open it again. */
const MAX_BYTES = 96 * 1024 * 1024;

export interface StoredFile {
  name: string;
  bytes: Uint8Array;
}

let connection: Promise<IDBDatabase | null> | null = null;

function db(): Promise<IDBDatabase | null> {
  if (connection) return connection;
  connection = new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return connection;
}

async function run<T>(mode: IDBTransactionMode, request: (store: IDBObjectStore) => IDBRequest): Promise<T | null> {
  const open = await db();
  if (!open) return null;
  return new Promise((resolve) => {
    try {
      const req = request(open.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result as T);
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

export async function putFile(sessionId: string, name: string, bytes: Uint8Array): Promise<void> {
  if (bytes.byteLength > MAX_BYTES) return;
  await run("readwrite", (s) => s.put({ name, bytes }, sessionId));
}

export async function getFile(sessionId: string): Promise<StoredFile | null> {
  const rec = await run<StoredFile>("readonly", (s) => s.get(sessionId));
  if (!rec?.bytes) return null;
  return { name: rec.name, bytes: new Uint8Array(rec.bytes) };
}

export async function deleteFile(sessionId: string): Promise<void> {
  await run("readwrite", (s) => s.delete(sessionId));
}

/** Drop files whose session is gone (deleted here, or trimmed away on another machine's list). */
export async function keepFilesFor(sessionIds: string[]): Promise<void> {
  const keys = await run<IDBValidKey[]>("readonly", (s) => s.getAllKeys());
  const keep = new Set(sessionIds);
  for (const k of keys ?? []) if (typeof k === "string" && !keep.has(k)) await deleteFile(k);
}

export async function clearFiles(): Promise<void> {
  await run("readwrite", (s) => s.clear());
}
