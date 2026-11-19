import { useCallback, useEffect, useMemo, useState } from "react";
import BusMap from "./components/BusMap";
import VehicleList from "./components/VehicleList";
import {
  getCatalog,
  getRoute,
  type NetworkCatalog,
  type RouteCollection,
} from "./api/network";
import {
  gpsQuality,
  inBounds,
  lineStyles,
  matchesFilters,
  UNKNOWN_COLOR,
  type Bounds,
  type Selection,
} from "./network";
import { usePositions } from "./usePositions";
import "./App.css";

export default function App() {
  const { snapshot, error, loading, now, stale, age, retry } = usePositions();
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection>({});
  const [areas, setAreas] = useState<string[]>([]);
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const [fitRequest, setFitRequest] = useState(0);
  const [catalog, setCatalog] = useState<NetworkCatalog | null>(null);
  const [routes, setRoutes] = useState<RouteCollection[]>([]);
  const [routeMissing, setRouteMissing] = useState<number[]>([]);
  const [loadedRoutesKey, setLoadedRoutesKey] = useState("");
  const [routeRetry, setRouteRetry] = useState(0);
  const styles = useMemo(() => lineStyles(catalog), [catalog]);
  const onBounds = useCallback((value: Bounds) => setBounds(value), []);

  useEffect(() => {
    const controller = new AbortController();
    const update = () =>
      getCatalog(controller.signal)
        .then(setCatalog)
        .catch(() => {
          /* Live positions remain usable. */
        });
    void update();
    const timer = setInterval(() => void update(), 60_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  const vehicles = useMemo(
    () =>
      !snapshot || stale
        ? []
        : snapshot.vehicles.filter((bus) =>
            matchesFilters(bus, selection, areas, styles),
          ),
    [snapshot, stale, selection, areas, styles],
  );
  const visible = useMemo(
    () => vehicles.filter((bus) => inBounds(bus, bounds)),
    [vehicles, bounds],
  );
  // Use the server collection age to tolerate local clock skew.
  const observedNow = snapshot
    ? Date.parse(snapshot.collected_at) + age * 1000
    : now;
  const summary = useMemo(() => {
    const lines = new Set(visible.map((bus) => bus.line));
    const quality = { recent: 0, old: 0, unknown: 0 };
    visible.forEach((bus) => quality[gpsQuality(bus, observedNow)]++);
    return { lines: lines.size, ...quality };
  }, [visible, observedNow]);
  const lineGroups = useMemo(() => {
    const groups = new Map<
      string,
      {
        label: string;
        senses: { id: number; direction: number; destination: string }[];
      }
    >();
    for (const item of snapshot?.lines ?? []) {
      const key = String(styles.get(item.id)?.area ?? "unknown");
      if (areas.length && !areas.includes(key)) continue;
      const group = groups.get(item.label) ?? { label: item.label, senses: [] };
      group.senses.push(item);
      groups.set(item.label, group);
    }
    const search = query.trim().toLocaleLowerCase("pt-BR");
    return [...groups.values()]
      .filter((g) =>
        `${g.label} ${g.senses.map((s) => s.destination).join(" ")}`
          .toLocaleLowerCase("pt-BR")
          .includes(search),
      )
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [snapshot?.lines, query, styles, areas]);
  const selectedIds = useMemo(
    () =>
      (snapshot?.lines ?? [])
        .filter((l) => {
          const chosen = selection[l.label];
          return (
            chosen !== undefined &&
            (chosen === "both" || chosen === l.direction) &&
            (!areas.length ||
              areas.includes(String(styles.get(l.id)?.area ?? "unknown")))
          );
        })
        .map((l) => l.id),
    [selection, snapshot?.lines, areas, styles],
  );
  const routeKey = selectedIds.join(",");
  const expectedRoutesKey = `${catalog?.version}:${routeKey}:${routeRetry}`;
  const routesLoading = loadedRoutesKey !== expectedRoutesKey;
  useEffect(() => {
    const controller = new AbortController();
    const ids = routeKey ? routeKey.split(",").map(Number) : [];
    if (!ids.length || !catalog?.version) return;
    let disposed = false;
    const version = catalog.version;
    void Promise.all(
      ids.map(async (id) => {
        try {
          return { id, route: await getRoute(id, version, controller.signal) };
        } catch {
          return { id, route: null };
        }
      }),
    ).then((results) => {
      if (disposed) return;
      setRoutes(results.flatMap((r) => (r.route ? [r.route] : [])));
      setRouteMissing(results.filter((r) => !r.route).map((r) => r.id));
      setLoadedRoutesKey(`${version}:${routeKey}:${routeRetry}`);
    });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [routeKey, catalog?.version, routeRetry]);
  function changeSelection(value: Selection) {
    setSelection(value);
  }
  function toggleArea(id: string) {
    setAreas((current) =>
      current.includes(id) ? current.filter((a) => a !== id) : [...current, id],
    );
  }
  const activeRoutes = useMemo(
    () =>
      routes
        .filter((r) => r.version === catalog?.version)
        .map((r) => ({
          ...r,
          features: r.features.filter((f) =>
            selectedIds.includes(f.properties.line_id),
          ),
        })),
    [routes, catalog?.version, selectedIds],
  );
  const collected = snapshot
    ? new Date(snapshot.collected_at).toLocaleTimeString("pt-BR", {
        timeZone: "America/Sao_Paulo",
      })
    : "—";
  const selectedLabels = Object.keys(selection);
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    visible.forEach((bus) => map.set(bus.line, (map.get(bus.line) ?? 0) + 1));
    return map;
  }, [visible]);
  const areaCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const bus of snapshot && !stale ? snapshot.vehicles : []) {
      const area = String(styles.get(bus.line_id)?.area ?? "unknown");
      map.set(area, (map.get(area) ?? 0) + 1);
    }
    return map;
  }, [snapshot, stale, styles]);

  return (
    <main className="map-app">
      <section className="map-surface" aria-label="Monitoramento ao vivo">
        <BusMap
          vehicles={vehicles}
          selection={selection}
          styles={styles}
          routes={activeRoutes}
          now={Math.floor(observedNow / 15000) * 15000}
          onBounds={onBounds}
          fitRequest={fitRequest}
        />
      </section>
      <aside className="explorer" aria-label="Explorar rede">
        <header className="explorer-header">
          <a className="brand" href="#line-search">
            <span className="brand-icon" aria-hidden="true">
              ↗
            </span>
            <span>
              ObservaÔnibus<small>SÃO PAULO</small>
            </span>
          </a>
          <span className="public-label">Mapa público</span>
        </header>
        <div className="explorer-body">
          <h1>A rede, em movimento.</h1>
          <p className="intro">
            Explore áreas, compare linhas e acompanhe a operação.
          </p>
          <section
            className="network-summary"
            aria-label="Resumo da área visível"
          >
            <div className="results-heading">
              <span>NESTA ÁREA DO MAPA</span>
              <span>
                {areas.length || selectedLabels.length
                  ? "Com filtros"
                  : "Toda a rede"}
              </span>
            </div>
            <div className="summary-grid">
              <div>
                <strong>
                  {stale || !snapshot
                    ? "—"
                    : visible.length.toLocaleString("pt-BR")}
                </strong>
                <span>veículos</span>
              </div>
              <div>
                <strong>{stale || !snapshot ? "—" : summary.lines}</strong>
                <span>linhas</span>
              </div>
              <div>
                <strong>
                  {visible.length
                    ? `${Math.round((summary.recent / visible.length) * 100)}%`
                    : "—"}
                </strong>
                <span>GPS recente</span>
              </div>
            </div>
            <p className="network-total">
              Rede:{" "}
              {stale || !snapshot
                ? "—"
                : snapshot.vehicles.length.toLocaleString("pt-BR")}{" "}
              veículos ·{" "}
              {stale || !snapshot
                ? "—"
                : new Set(snapshot.vehicles.map((v) => v.line)).size}{" "}
              linhas
            </p>
            <details className="quality-details">
              <summary>Qualidade dos dados</summary>
              <p>
                {summary.recent} recentes · {summary.old} antigos ·{" "}
                {summary.unknown} desconhecidos
              </p>
              <p>
                Percentual calculado sobre todos os veículos observados nesta
                área, incluindo os de horário desconhecido. GPS recente: até 60
                s.
              </p>
            </details>
          </section>
          <details className="area-filter">
            <summary>
              Áreas de operação{" "}
              <b className="area-palette" aria-hidden="true">
                {catalog?.areas.map((a) => (
                  <i key={a.id} style={{ background: a.color }} />
                ))}
              </b>
              <span>
                {areas.length ? `${areas.length} selecionadas` : "Todas"}
              </span>
            </summary>
            <div className="area-options">
              {(catalog?.areas ?? []).map((area) => (
                <label key={area.id}>
                  <input
                    type="checkbox"
                    checked={areas.includes(String(area.id))}
                    onChange={() => toggleArea(String(area.id))}
                  />
                  <i style={{ background: area.color }} />
                  {area.id} · {area.name}
                  <small>{areaCounts.get(String(area.id)) ?? 0}</small>
                </label>
              ))}
              <label>
                <input
                  type="checkbox"
                  checked={areas.includes("unknown")}
                  onChange={() => toggleArea("unknown")}
                />
                <i style={{ background: UNKNOWN_COLOR }} />
                Área não identificada
                <small>{areaCounts.get("unknown") ?? 0}</small>
              </label>
            </div>
          </details>
          {catalog?.status !== "ready" && (
            <p className="catalog-note">
              Cores e percursos planejados indisponíveis no momento. As posições continuam disponíveis.
            </p>
          )}
          {catalog?.synthetic && (
            <p className="synthetic-banner" role="status">
              Catálogo de demonstração · dados sintéticos
            </p>
          )}
          <label className="search-label" htmlFor="line-search">
            Linha ou destino
          </label>
          <div className="search-box">
            <span aria-hidden="true">⌕</span>
            <input
              id="line-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Adicionar linhas à comparação"
              autoComplete="off"
            />
          </div>
          {!!selectedLabels.length && (
            <div className="selected-lines" aria-label="Linhas selecionadas">
              {selectedLabels.map((label) => {
                const senses = (snapshot?.lines ?? []).filter(
                  (l) => l.label === label,
                );
                const colors = [
                  ...new Set(
                    senses.map((s) => styles.get(s.id)?.color ?? UNKNOWN_COLOR),
                  ),
                ];
                return (
                  <div
                    className="line-chip"
                    key={label}
                    style={{ borderLeftColor: colors[0] }}
                  >
                    <span>{label}</span>
                    <select
                      aria-label={`Sentido da linha ${label}`}
                      value={selection[label]}
                      onChange={(e) =>
                        changeSelection({
                          ...selection,
                          [label]:
                            e.target.value === "both"
                              ? "both"
                              : Number(e.target.value),
                        })
                      }
                    >
                      <option value="both">Ambos os sentidos</option>
                      {[
                        ...new Map(
                          senses.map((s) => [s.direction, s]),
                        ).values(),
                      ].map((s) => (
                        <option key={s.direction} value={s.direction}>
                          {s.direction} · {s.destination}
                        </option>
                      ))}
                    </select>
                    <button
                      aria-label={`Remover linha ${label}`}
                      onClick={() => {
                        const next = { ...selection };
                        delete next[label];
                        changeSelection(next);
                      }}
                    >
                      ×
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          <div className="results-heading">
            <span>{query ? "RESULTADOS" : "LINHAS OBSERVADAS"}</span>
            <span>{lineGroups.length} linhas</span>
          </div>
          <div className="line-results">
            {lineGroups.slice(0, 6).map((group) => {
              const color =
                styles.get(group.senses[0].id)?.color ?? UNKNOWN_COLOR;
              return (
                <button
                  key={group.label}
                  className={`line-result ${selection[group.label] !== undefined ? "is-selected" : ""}`}
                  aria-pressed={selection[group.label] !== undefined}
                  onClick={() => {
                    const next = { ...selection };
                    if (next[group.label] !== undefined)
                      delete next[group.label];
                    else next[group.label] = "both";
                    changeSelection(next);
                  }}
                >
                  <span
                    className="line-code"
                    style={{ borderLeft: `4px solid ${color}` }}
                  >
                    {group.label}
                  </span>
                  <span className="line-destination">
                    {group.senses
                      .map((s) => s.destination)
                      .filter((v, i, a) => a.indexOf(v) === i)
                      .join(" / ")}
                    <small>
                      {counts.get(group.label) ?? 0} veículos nesta área ·{" "}
                      {group.senses.length} sentidos disponíveis
                    </small>
                  </span>
                  <span aria-hidden="true">
                    {selection[group.label] !== undefined ? "✓" : "+"}
                  </span>
                </button>
              );
            })}
            {!lineGroups.length && (
              <p className="empty-results">
                {loading
                  ? "Buscando linhas…"
                  : "Nenhuma linha encontrada neste filtro."}
              </p>
            )}
          </div>
          <p className="search-hint">
            Busque para adicionar outras linhas. A seleção mantém ambos os
            sentidos.
          </p>
          <div className="selection-actions">
            <button
              onClick={() => setFitRequest((v) => v + 1)}
              disabled={!vehicles.length}
            >
              Enquadrar seleção
            </button>
            <button
              onClick={() => {
                changeSelection({});
                setAreas([]);
                setQuery("");
              }}
            >
              Limpar filtros
            </button>
          </div>
          {!!selectedLabels.length && (
            <p className="route-note">
              {!catalog?.version
                ? "Percurso planejado indisponível: nenhuma referência GTFS carregada."
                : !selectedIds.length
                  ? "Nenhum sentido selecionado nas áreas filtradas."
                  : routesLoading
                    ? "Carregando percursos…"
                    : routeMissing.length
                      ? `Percurso planejado indisponível em ${routeMissing.length} sentidos nesta versão.`
                      : "Percursos planejados · versão GTFS identificada."}
            </p>
          )}
          {!!selectedLabels.length &&
            !!routeMissing.length &&
            !routesLoading && (
              <button
                className="retry-routes"
                onClick={() => setRouteRetry((v) => v + 1)}
              >
                Tentar carregar percursos
              </button>
            )}
          <VehicleList vehicles={visible} />
        </div>
        <footer className="explorer-footer">
          <span className={`status-dot ${error || stale ? "offline" : ""}`} />
          <span>
            {loading
              ? "Conectando"
              : stale
                ? "Dados desatualizados"
                : error
                  ? "Atualização interrompida"
                  : "Atualização ativa"}
          </span>
          <span className="collection-time">{collected}</span>
        </footer>
      </aside>
      <div className="map-caption">
        <span className="caption-dot" />
        <span>
          {catalog?.synthetic ? "Demonstração sintética · " : ""}
          {selectedLabels.length
            ? `${selectedLabels.length} linhas na comparação`
            : "Visão geral da rede"}{" "}
          · grupos por proximidade
        </span>
      </div>
      {(stale || error) && (
        <div className="connection-notice" role="status">
          <strong>
            {stale ? "As posições expiraram" : "Não foi possível atualizar"}
          </strong>
          <p>
            {stale ? "Posições ocultas após 60 s sem coleta recente." : error}
          </p>
          <button onClick={retry}>Tentar atualizar</button>
        </div>
      )}
      <details className="map-info">
        <summary>Legenda e fontes</summary>
        <p>
          Cores: áreas oficiais SPTrans. Amostras adaptadas para tela; área
          desconhecida em cinza.
        </p>
        <p>
          Bolhas neutras mostram quantidades de ônibus; amplie para ver as
          posições individuais. Sentido 1: traço contínuo · sentido 2:
          tracejado. GPS antigo/desconhecido: ponto vazado e menor opacidade.
        </p>
        <p>
          SPTrans / Olho Vivo · coleta {collected} (Brasília). Ausência de GPS
          não comprova viagem não realizada.
        </p>
        {catalog?.version && (
          <p>
            GTFS: {catalog.version.slice(0, 12)} · captura{" "}
            {catalog.captured_at
              ? new Date(catalog.captured_at).toLocaleDateString("pt-BR")
              : "não informada"}
            . A data de captura não comprova vigência.
          </p>
        )}
      </details>
    </main>
  );
}
