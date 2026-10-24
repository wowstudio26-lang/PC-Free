import Dexie from 'dexie';

const db = new Dexie('CloudPC_DB');
db.version(1).stores({
  notes: 'id, updatedAt',
  files: '++id, name, type, updatedAt',
  settings: 'key'
});

export async function saveNote(id, content) {
  await db.notes.put({ id, content, updatedAt: new Date().toISOString() });
}
export async function getNote(id) {
  return (await db.notes.get(id))?.content ?? '';
}
export async function listFiles() {
  return db.files.orderBy('name').toArray();
}
export async function addFile(file) {
  return db.files.add({
    name: file.name,
    type: file.type || 'application/octet-stream',
    size: file.size,
    updatedAt: new Date().toISOString()
  });
}
export async function deleteFile(id) {
  return db.files.delete(id);
}
export default db;
