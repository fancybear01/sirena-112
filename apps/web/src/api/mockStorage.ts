export const teacherSessionStorageKey = 'sirena-112:teacher-session';
export const studentDraftStorageKey = 'sirena-112:student-assignment';

export function getBrowserStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}
