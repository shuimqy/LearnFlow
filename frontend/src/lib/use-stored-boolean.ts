"use client";

import { useCallback, useEffect, useState } from "react";

export function useStoredBoolean(key: string, fallback = false) {
  const [value, setValue] = useState(fallback);
  useEffect(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored !== null) setValue(stored === "true");
    } catch {}
  }, [key]);
  const update = useCallback(
    (next: boolean) => {
      setValue(next);
      try {
        localStorage.setItem(key, String(next));
      } catch {}
    },
    [key],
  );
  return [value, update] as const;
}
