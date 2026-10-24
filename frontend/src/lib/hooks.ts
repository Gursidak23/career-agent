import { useEffect, useRef, useState } from "react";

/** useState that survives reloads and page switches (localStorage, best effort). */
export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable (private mode): keep in-memory state */
    }
  }, [key, value]);
  return [value, setValue] as const;
}

export function useDebounced<T>(value: T, ms = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

/** Seconds elapsed while `running` is true; resets when it starts again. */
export function useElapsed(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  const start = useRef(0);
  useEffect(() => {
    if (!running) return;
    start.current = Date.now();
    setSeconds(0);
    const t = window.setInterval(
      () => setSeconds(Math.floor((Date.now() - start.current) / 1000)),
      1000
    );
    return () => window.clearInterval(t);
  }, [running]);
  return seconds;
}

export function formatDate(iso: string): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function titleCase(name: string): string {
  return name === name.toUpperCase()
    ? name.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())
    : name;
}
