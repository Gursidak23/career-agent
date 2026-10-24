import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Kind = "ok" | "err" | "warn" | "info";
interface ToastItem {
  id: number;
  kind: Kind;
  text: string;
}

const ToastContext = createContext<(kind: Kind, text: string) => void>(() => {});

/** Fixed-position notifications, so feedback is visible wherever the page is scrolled. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((all) => all.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (kind: Kind, text: string) => {
      const id = Date.now() + Math.random();
      setItems((all) => [...all.slice(-3), { id, kind, text }]);
      // Errors and warnings stay until dismissed; they usually need action.
      if (kind === "ok" || kind === "info") window.setTimeout(() => dismiss(id), 4500);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <span>{t.text}</span>
            <button className="toast-close" onClick={() => dismiss(t.id)} aria-label="Dismiss">
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastContext);
  return {
    ok: (text: string) => push("ok", text),
    err: (text: string) => push("err", text),
    warn: (text: string) => push("warn", text),
    info: (text: string) => push("info", text),
  };
}
