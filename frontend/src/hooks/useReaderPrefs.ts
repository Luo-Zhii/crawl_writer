import { useCallback, useEffect, useState } from "react";

export interface ReaderPrefs {
  fontSize: number;
  lineHeight: number;
  width: number;
  /** Prefer the translation when a chapter has one. */
  translated: boolean;
}

const STORAGE_KEY = "crawlw.reader";

const DEFAULTS: ReaderPrefs = {
  fontSize: 18,
  lineHeight: 1.8,
  width: 42,
  translated: true,
};

export const FONT_RANGE = { min: 14, max: 28, step: 1 };
export const WIDTH_RANGE = { min: 30, max: 70, step: 2 };

function load(): ReaderPrefs {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) return DEFAULTS;
    // Merge so a stored object from an older version still works.
    return { ...DEFAULTS, ...(JSON.parse(saved) as Partial<ReaderPrefs>) };
  } catch {
    return DEFAULTS;
  }
}

/**
 * Reading preferences, kept on the device.
 *
 * Font size and column width are about the screen in front of you, so unlike
 * reading position they stay local rather than going to the server.
 */
export function useReaderPrefs() {
  const [prefs, setPrefs] = useState<ReaderPrefs>(load);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  }, [prefs]);

  const update = useCallback((changes: Partial<ReaderPrefs>) => {
    setPrefs((current) => ({ ...current, ...changes }));
  }, []);

  const reset = useCallback(() => setPrefs(DEFAULTS), []);

  return { prefs, update, reset };
}
