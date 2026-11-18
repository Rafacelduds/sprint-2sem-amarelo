import { useEffect, useState } from "react";
import { getPositions, type Snapshot } from "./api/positions";
export function usePositions() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [receivedAt, setReceivedAt] = useState(0);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    async function update() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 20_000);
      try {
        const data = await getPositions(controller.signal);
        if (disposed) return;
        setSnapshot(data);
        setReceivedAt(Date.now());
        setError("");
      } catch {
        if (!disposed)
          setError(
            "Conexão com a fonte indisponível. Tentaremos novamente automaticamente.",
          );
      } finally {
        clearTimeout(timeout);
        if (!disposed) {
          setLoading(false);
          timer = setTimeout(update, 15_000);
        }
      }
    }
    void update();
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [retry]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Use the server's age plus elapsed local time, tolerating client clock skew.
  const age = snapshot
    ? Math.max(
        0,
        (Date.parse(snapshot.served_at) -
          Date.parse(snapshot.collected_at) +
          Math.max(0, now - receivedAt)) /
          1000,
      )
    : 0;
  const stale =
    !!snapshot && (snapshot.stale || !Number.isFinite(age) || age > 60);

  return {
    snapshot,
    error,
    loading,
    now,
    stale,
    age,
    retry: () => setRetry((v) => v + 1),
  };
}
