/** POST /api/atlas/folder: the folder's atlas was opened, or a new one would be made from its screenshots. */
export type FolderOpened = { opened: string; new: string[]; others: number } | { create: number };
