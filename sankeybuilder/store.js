const DB_NAME = "sankeybuilder";
const DB_VERSION = 1;
const STORE = "docs";
const KEY = "current";

export function memoryStore(seed = null) {
  let data = seed ? structuredClone(seed) : null;
  return {
    async get() {
      return data ? structuredClone(data) : null;
    },
    async set(doc) {
      data = structuredClone(doc);
    },
    async clear() {
      data = null;
    },
  };
}

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export function idbStore() {
  return {
    async get() {
      const db = await open();
      try {
        return await new Promise((resolve, reject) => {
          const tx = db.transaction(STORE, "readonly");
          const req = tx.objectStore(STORE).get(KEY);
          req.onsuccess = () => resolve(req.result || null);
          req.onerror = () => reject(req.error);
        });
      } finally {
        db.close();
      }
    },
    async set(doc) {
      const db = await open();
      try {
        await new Promise((resolve, reject) => {
          const tx = db.transaction(STORE, "readwrite");
          tx.objectStore(STORE).put(doc, KEY);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      } finally {
        db.close();
      }
    },
    async clear() {
      const db = await open();
      try {
        await new Promise((resolve, reject) => {
          const tx = db.transaction(STORE, "readwrite");
          tx.objectStore(STORE).delete(KEY);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      } finally {
        db.close();
      }
    },
  };
}
