'use client';

import { useSyncExternalStore } from 'react';

// The three colour themes (values live in globals.css under [data-theme]). The swatch shows each
// theme's frame colour and its marker, so people pick by looking rather than by name.
const THEMES = [
  { id: 'highlighter', label: 'Highlighter', frame: '#18213a', marker: '#ffd23f' },
  { id: 'evergreen', label: 'Evergreen', frame: '#10372f', marker: '#d6f26e' },
  { id: 'night', label: 'Night', frame: '#0c111a', marker: '#ffd23f' },
] as const;

const STORAGE_KEY = 'motif-theme';
const CHANGED = 'motif:theme-changed';

const subscribe = (onChange: () => void) => {
  window.addEventListener(CHANGED, onChange);
  return () => window.removeEventListener(CHANGED, onChange);
};
const currentTheme = () => document.documentElement.dataset.theme || 'highlighter';

function applyTheme(id: string) {
  document.documentElement.dataset.theme = id;
  try { localStorage.setItem(STORAGE_KEY, id); } catch { /* private mode: the choice lasts until reload */ }
  window.dispatchEvent(new Event(CHANGED));
}

/** Three swatches in the top bar. The choice is remembered in this browser. */
export default function ThemePicker() {
  const theme = useSyncExternalStore(subscribe, currentTheme, () => 'highlighter');
  return (
    <div role="radiogroup" aria-label="Colour theme" className="flex items-center gap-1.5">
      {THEMES.map((item) => (
        <button
          key={item.id}
          role="radio"
          aria-checked={theme === item.id}
          aria-label={`${item.label} theme`}
          title={item.label}
          onClick={() => applyTheme(item.id)}
          className={`h-[18px] w-[18px] rounded-full ring-1 ring-on-chrome/35 transition-shadow ${theme === item.id ? 'ring-2 ring-on-chrome ring-offset-2 ring-offset-chrome' : 'hover:ring-on-chrome-muted'}`}
          style={{ background: `linear-gradient(135deg, ${item.frame} 0 50%, ${item.marker} 50% 100%)` }}
        />
      ))}
    </div>
  );
}
