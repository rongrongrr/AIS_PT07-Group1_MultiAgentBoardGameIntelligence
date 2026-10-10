import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { applyTheme, readThemePref, resolveTheme, THEME_KEY, useTheme } from './theme';

function mockOs(light: boolean) {
  const listeners: (() => void)[] = [];
  const mq = {
    matches: light,
    addEventListener: (_: string, f: () => void) => listeners.push(f),
    removeEventListener: (_: string, f: () => void) => listeners.splice(listeners.indexOf(f), 1),
  };
  window.matchMedia = vi.fn().mockReturnValue(mq) as never;
  return { mq, fire: () => listeners.forEach((f) => f()), listeners };
}

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute('data-theme'); });
afterEach(() => { vi.restoreAllMocks(); delete (window as { matchMedia?: unknown }).matchMedia; });

describe('theme helpers', () => {
  it('reads only valid preferences and defaults to dark', () => {
    expect(readThemePref()).toBe('dark');
    localStorage.setItem(THEME_KEY, 'light'); expect(readThemePref()).toBe('light');
    localStorage.setItem(THEME_KEY, 'system'); expect(readThemePref()).toBe('system');
    localStorage.setItem(THEME_KEY, 'neon'); expect(readThemePref()).toBe('dark');
  });

  it('resolves system from the operating system, and falls back to dark without matchMedia', () => {
    expect(resolveTheme('system')).toBe('dark');
    mockOs(true); expect(resolveTheme('system')).toBe('light');
    expect(resolveTheme('dark')).toBe('dark');
    expect(applyTheme('light')).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });
});

function Probe() {
  const [pref, setPref] = useTheme();
  return <button onClick={() => setPref(pref === 'light' ? 'dark' : 'light')}>{pref}</button>;
}

describe('useTheme', () => {
  it('applies and persists the choice, and stays dark by default even on a light OS', () => {
    mockOs(true);
    render(<Probe />);
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    fireEvent.click(screen.getByRole('button'));                       // dark -> light
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(localStorage.getItem(THEME_KEY)).toBe('light');
    fireEvent.click(screen.getByRole('button'));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('follows the operating system while set to system, and stops following otherwise', () => {
    const os = mockOs(false);
    localStorage.setItem(THEME_KEY, 'system');
    const { unmount } = render(<Probe />);
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(os.listeners).toHaveLength(1);
    os.mq.matches = true;
    act(() => os.fire());
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    unmount();
    expect(os.listeners).toHaveLength(0);                              // listener removed on unmount
  });
});
