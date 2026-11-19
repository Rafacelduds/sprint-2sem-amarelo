import { useEffect, useMemo, useRef, useState } from "react";
import { getRoute, type RouteCollection } from "./api/network";
const CONCURRENCY = 4;
const CACHE_LIMIT = 512;
type Result = {
  key: string;
  routes: RouteCollection[];
  missing: number[];
  completed: number;
};
export function useNetworkRoutes(
  ids: number[],
  version: string | null | undefined,
  retry: number,
) {
  const idsKey = ids.join(",");
  const key = `${version}:${idsKey}:${retry}`;
  const cache = useRef<{
    version: string | null;
    entries: Map<number, RouteCollection | null>;
  }>({ version: null, entries: new Map() });
  const previousRetry = useRef(retry);
  const [result, setResult] = useState<Result>({
    key: "",
    routes: [],
    missing: [],
    completed: 0,
  });
  useEffect(() => {
    if (!idsKey || !version) return;
    const requested = idsKey.split(",").map(Number);
    if (cache.current.version !== version)
      cache.current = { version, entries: new Map() };
    const entries = cache.current.entries;
    if (retry !== previousRetry.current)
      for (const id of requested)
        if (entries.get(id) === null) entries.delete(id);
    previousRetry.current = retry;
    const controller = new AbortController();
    const results = new Map<number, RouteCollection | null>();
    const queue: number[] = [];
    for (const id of requested) {
      if (entries.has(id)) results.set(id, entries.get(id)!);
      else queue.push(id);
    }
    let cursor = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const publish = () => {
      if (controller.signal.aborted) return;
      setResult({
        key: `${version}:${idsKey}:${retry}`,
        routes: [...results.values()].filter(
          (r): r is RouteCollection => r !== null,
        ),
        missing: [...results].filter(([, r]) => r === null).map(([id]) => id),
        completed: results.size,
      });
    };
    const schedule = () => {
      if (!timer)
        timer = setTimeout(() => {
          timer = undefined;
          publish();
        }, 100);
    };
    async function worker() {
      while (!controller.signal.aborted && cursor < queue.length) {
        const id = queue[cursor++];
        let route: RouteCollection | null;
        try {
          route = await getRoute(id, version!, controller.signal);
          if (route.version !== version) route = null;
        } catch {
          if (controller.signal.aborted) return;
          route = null;
        }
        if (controller.signal.aborted) return;
        results.set(id, route);
        entries.delete(id);
        entries.set(id, route);
        while (entries.size > CACHE_LIMIT)
          entries.delete(entries.keys().next().value!);
        schedule();
      }
    }
    // Publish cached hits asynchronously, then coalesce arrivals to avoid a render per route.
    void Promise.resolve().then(publish);
    void Promise.all(
      Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker),
    ).then(() => {
      if (timer) clearTimeout(timer);
      publish();
    });
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [idsKey, version, retry]);
  const routes = useMemo(() => {
    const requested = new Set(idsKey.split(",").filter(Boolean).map(Number));
    return result.routes.filter(
      (route) =>
        route.version === version &&
        route.features.some((f) => requested.has(f.properties.line_id)),
    );
  }, [result.routes, version, idsKey]);
  const completed = result.key === key ? result.completed : 0;
  const loading = Boolean(
    version && ids.length && (result.key !== key || completed < ids.length),
  );
  return {
    routes,
    missing: result.key === key ? result.missing : [],
    completed,
    loading,
  };
}
