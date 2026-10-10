import { useCallback, useState } from 'react';

/** localStorage that never throws (private windows, blocked storage). */
export function readPref(key: string, fallback = ''): string {
  try { return window.localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}

export function writePref(key: string, value: string): void {
  try { window.localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

/** A string preference that survives reloads. */
export function usePref(key: string, fallback = ''): [string, (v: string) => void] {
  const [value, setValue] = useState(() => readPref(key, fallback));
  const set = useCallback((v: string) => { setValue(v); writePref(key, v); }, [key]);
  return [value, set];
}

/** A boolean preference that survives reloads. */
export function useFlag(key: string, fallback = false): [boolean, (v: boolean) => void] {
  const [raw, setRaw] = usePref(key, fallback ? '1' : '0');
  return [raw === '1', (v: boolean) => setRaw(v ? '1' : '0')];
}
