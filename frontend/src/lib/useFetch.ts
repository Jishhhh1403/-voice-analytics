import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

type State<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
  setData: (value: T | null) => void;
};

export function useFetch<T>(path: string | null, deps: unknown[] = []): State<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const requestId = useRef(0);

  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    const current = ++requestId.current;
    setLoading(true);
    setError(null);
    api<T>(path)
      .then((value) => {
        if (current === requestId.current) setData(value);
      })
      .catch((err: Error) => {
        if (current === requestId.current) setError(err.message);
      })
      .finally(() => {
        if (current === requestId.current) setLoading(false);
      });
  }, [path, tick, ...deps]);

  return { data, loading, error, reload, setData };
}

export function usePolling(callback: () => void, active: boolean, interval = 2500): void {
  const saved = useRef(callback);
  saved.current = callback;
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => saved.current(), interval);
    return () => window.clearInterval(timer);
  }, [active, interval]);
}
