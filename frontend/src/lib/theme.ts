import { useEffect, useState } from 'react';
import { readPref, writePref } from './prefs';

export type ThemePref = 'system' | 'light' | 'dark';
export const THEME_KEY = 'tiles_theme';

export function readThemePref(): ThemePref {
  const v = readPref(THEME_KEY, 'dark');           // dark unless the user chose otherwise
  return v === 'light' || v === 'system' ? v : 'dark';
}

/** The theme that is actually shown for a preference ("system" follows the operating system). */
export function resolveTheme(pref: ThemePref): 'light' | 'dark' {
  if (pref !== 'system') return pref;
  try { return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'; } catch { return 'dark'; }
}

/** Sets data-theme on <html>; the CSS (index.css) swaps the palette from that attribute. */
export function applyTheme(pref: ThemePref): 'light' | 'dark' {
  const theme = resolveTheme(pref);
  document.documentElement.setAttribute('data-theme', theme);
  return theme;
}

/** The theme preference, kept in localStorage and applied to the page; follows the OS while on "system". */
export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPrefState] = useState<ThemePref>(readThemePref);

  useEffect(() => {
    applyTheme(pref);
    if (pref !== 'system') return;
    let mq: MediaQueryList | undefined;
    try { mq = window.matchMedia('(prefers-color-scheme: light)'); } catch { return; }
    const onChange = () => applyTheme('system');
    mq.addEventListener('change', onChange);
    return () => mq!.removeEventListener('change', onChange);
  }, [pref]);

  return [pref, (p) => { writePref(THEME_KEY, p); setPrefState(p); }];
}
