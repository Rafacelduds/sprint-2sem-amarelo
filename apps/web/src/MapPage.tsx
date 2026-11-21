import CollectionCoverage from "./CollectionCoverage";
import { useCallback, useEffect, useMemo, useState } from "react";
import BusMap from "./components/BusMap";
import RouteFocusPanel from "./components/RouteFocusPanel";
import { availableRouteLabels, effectiveRouteFocus } from "./routeFocus";
import PositionDetails from "./components/PositionDetails";
import VisualizationControls from "./components/VisualizationControls";
import { readVisual, VISUAL_KEY } from "./visualization";
import type { GroupSelection } from "./clusters";
import VehicleList from "./components/VehicleList";
import { getCatalog, type NetworkCatalog } from "./api/network";
import {
  gpsQuality,
  inBounds,
  lineStyles,
  matchesFilters,
  UNKNOWN_COLOR,
  type Bounds,
  type Selection,
} from "./network";
import { useNetworkRoutes } from "./useNetworkRoutes";
import { usePositions } from "./usePositions";
import "./App.css";

const NO_AREAS: string[] = [];

export default function MapPage() {
  const { snapshot, error, loading, now, stale, age, retry } = usePositions();
  const [query, setQuery] = useState("");
  const [visual, setVisual] = useState(readVisual);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [emphasizeAll, setEmphasizeAll] = useState(false);
  const [wantedRouteFocus, setWantedRouteFocus] = useState<string | null>(null);
  const [routePick, setRoutePick] = useState<{
    version: string | null;
    labels: string[];
  } | null>(null);
  const [routeScrollRequest, setRouteScrollRequest] = useState(0);
  const [group, setGroup] = useState<GroupSelection | null>(null);
  const onSelect = useCallback((id: string) => {
    setSelectedId(id);
    setRoutePick(null);
    setGroup(null);
  }, []);
  const onGroup = useCallback((value: GroupSelection | null) => {
    setGroup(value);
    if (value) setSelectedId(null);
  }, []);
  useEffect(() => {
    try {
      window.localStorage.setItem(VISUAL_KEY, JSON.stringify(visual));
    } catch {
      /* Optional local preference storage. */
    }
  }, [visual]);
  const [selection, setSelection] = useState<Selection>({});
  const [areas, setAreas] = useState<string[]>([]);
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const [fitRequest, setFitRequest] = useState(0);
  const [catalog, setCatalog] = useState<NetworkCatalog | null>(null);
  const [routeRetry, setRouteRetry] = useState(0);
  const styles = useMemo(() => lineStyles(catalog), [catalog]);
  // Preservar a intenção do usuário sem aplicar associações GTFS indisponíveis.
  const effectiveAreas = catalog?.status === "ready" ? areas : NO_AREAS;
  const onBounds = useCallback((value: Bounds) => setBounds(value), []);

  useEffect(() => {
    const controller = new AbortController();
    const update = () =>
      getCatalog(controller.signal)
        .then(setCatalog)
        .catch(() => {
          if (!controller.signal.aborted) setCatalog(null);
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
            matchesFilters(bus, selection, effectiveAreas, styles),
          ),
    [snapshot, stale, selection, effectiveAreas, styles],
  );
  const selectedVehicle = vehicles.find((bus) => bus.id === selectedId) ?? null;
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
      if (effectiveAreas.length && !effectiveAreas.includes(key)) continue;
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
  }, [snapshot?.lines, query, styles, effectiveAreas]);
  const selectedIds = useMemo(
    () =>
      (snapshot?.lines ?? [])
        .filter((l) => {
          const chosen = selection[l.label];
          return (
            chosen !== undefined &&
            (chosen === "both" || chosen === l.direction) &&
            (!effectiveAreas.length ||
              effectiveAreas.includes(String(styles.get(l.id)?.area ?? "unknown")))
          );
        })
        .map((l) => l.id),
    [selection, snapshot?.lines, effectiveAreas, styles],
  );
  const areaRouteScope =
    effectiveAreas.length > 0 && Object.keys(selection).length === 0;
  const routeIds = useMemo(() => {
    if (!areaRouteScope) return [...selectedIds].sort((a, b) => a - b);
    return (catalog?.lines ?? [])
      .filter((line) => effectiveAreas.includes(String(line.area_id ?? "unknown")))
      .map((line) => line.line_id)
      .sort((a, b) => a - b);
  }, [areaRouteScope, effectiveAreas, catalog?.lines, selectedIds]);
  const {
    routes,
    missing: routeMissing,
    completed: routesCompleted,
    loading: routesLoading,
  } = useNetworkRoutes(routeIds, catalog?.version, routeRetry);
  function changeSelection(value: Selection) {
    const added = Object.keys(value).filter(
      (label) => selection[label] === undefined,
    );
    if (added.length) {
      setWantedRouteFocus(added[added.length - 1]);
      setEmphasizeAll(false);
    } else if (wantedRouteFocus && value[wantedRouteFocus] === undefined)
      setWantedRouteFocus(
        Object.keys(value)
          .reverse()
          .find((label) => availableLabels.has(label)) ?? null,
      );
    setRoutePick(null);
    setSelection(value);
  }
  function toggleArea(id: string) {
    setRoutePick(null);
    if (!Object.keys(selection).length) setWantedRouteFocus(null);
    setEmphasizeAll(false);
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
            routeIds.includes(f.properties.line_id),
          ),
        })),
    [routes, catalog?.version, routeIds],
  );
  const availableLabels = availableRouteLabels(activeRoutes);
  const routeFocus = effectiveRouteFocus(
    wantedRouteFocus,
    areaRouteScope ? [...availableLabels] : Object.keys(selection),
    availableLabels,
  );
  const chooseRoute = useCallback((label: string) => {
    setEmphasizeAll(false);
    setWantedRouteFocus(label);
    setRoutePick(null);
    setSelectedId(null);
    setGroup(null);
  }, []);
  const onRoutePick = useCallback(
    (labels: string[]) => {
      if (!labels.length) return;
      setSelectedId(null);
      setGroup(null);
      setEmphasizeAll(false);
      if (labels.length === 1) {
        setWantedRouteFocus(labels[0]);
        setRoutePick(null);
      } else setRoutePick({ version: catalog?.version ?? null, labels });
      setRouteScrollRequest((request) => request + 1);
    },
    [catalog?.version],
  );
  const routeCandidates =
    routePick?.version === catalog?.version
      ? (routePick?.labels.filter((label) => availableLabels.has(label)) ?? [])
      : [];
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
          visual={visual}
          selected={selectedVehicle}
          onSelect={onSelect}
          onGroup={onGroup}
          styles={styles}
          routes={activeRoutes}
          routeFocus={routeFocus}
          areaRoutes={areaRouteScope}
          routeOverview={areaRouteScope && routeFocus === null && !emphasizeAll}
          onRoutePick={onRoutePick}
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
          <CollectionCoverage />
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
          <PositionDetails
            selectedId={selectedId}
            vehicle={selectedVehicle}
            group={group}
            styles={styles}
            collectedAt={snapshot?.collected_at ?? null}
            now={observedNow}
            onSelect={onSelect}
            onClose={() => {
              setSelectedId(null);
              setGroup(null);
            }}
          />
          <RouteFocusPanel
            available={availableLabels.size}
            overview={areaRouteScope && routeFocus === null && !emphasizeAll}
            focus={routeFocus}
            destinations={[
              ...new Set(
                activeRoutes
                  .flatMap((route) => route.features)
                  .filter((feature) => feature.properties.label === routeFocus)
                  .map(
                    (feature) =>
                      `Sentido ${feature.properties.direction}: ${feature.properties.destination || "Destino não informado"}`,
                  ),
              ),
            ]}
            candidates={routeCandidates}
            scrollRequest={routeScrollRequest}
            onChoose={chooseRoute}
            onAll={() => {
              setWantedRouteFocus(null);
              setEmphasizeAll(true);
              setRoutePick(null);
            }}
            onDismiss={() => setRoutePick(null)}
          />
          <VisualizationControls value={visual} onChange={setVisual} />
          {visual.mode !== "clusters" && (
            <section
              className="density-legend"
              aria-label="Legenda de densidade"
            >
              <strong>Concentração de posições observadas</strong>
              <div className="density-scale" />
              <div className="density-labels">
                <span>Menor</span>
                <span>Maior</span>
              </div>
              <p>
                Inclui GPS antigo ou sem horário. A intensidade varia com o
                zoom; não indica cobertura, demanda ou qualidade do serviço.
              </p>
            </section>
          )}
          <details className="area-filter">
            <summary>
              Áreas de operação{" "}
              <b className="area-palette" aria-hidden="true">
                {catalog?.areas.map((a) => (
                  <i key={a.id} style={{ background: a.color }} />
                ))}
              </b>
              <span>
                {areas.length ? `${areas.length} selecionadas${catalog?.status === "ready" ? "" : " · suspensas"}` : "Todas"}
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
                  disabled={catalog?.status !== "ready"}
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
              Cores e percursos planejados indisponíveis no momento. As posições
              continuam disponíveis.
              {areas.length > 0 && <> Filtro por área suspenso até a referência
                voltar; filtros de linha e sentido continuam ativos.</>}
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
                    <button
                      className="line-focus-button"
                      aria-label={`Destacar linha ${label}`}
                      aria-pressed={routeFocus === label}
                      disabled={!availableLabels.has(label)}
                      onClick={() => chooseRoute(label)}
                    >
                      {label}
                      {routeFocus === label && <small>Em foco</small>}
                    </button>
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
              disabled={!vehicles.length && !availableLabels.size}
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
          {(selectedLabels.length > 0 || areas.length > 0) && (
            <p className="route-note" role="status">
              {!catalog?.version
                ? "Percurso planejado indisponível: nenhuma referência GTFS carregada."
                : !routeIds.length
                  ? "Nenhum percurso associado às áreas selecionadas no catálogo atual."
                  : routesLoading
                    ? `Carregando percursos… ${routesCompleted} de ${routeIds.length} sentidos consultados.`
                    : routeMissing.length
                      ? areaRouteScope
                        ? `${availableLabels.size} linhas exibidas · ${routeMissing.length} sentidos sem percurso nesta versão.`
                        : `Percurso planejado indisponível em ${routeMissing.length} sentidos nesta versão.`
                      : "Percursos planejados · versão GTFS identificada."}
            </p>
          )}
          {(selectedLabels.length > 0 || areas.length > 0) &&
            !!routeMissing.length &&
            !routesLoading && (
              <button
                className="retry-routes"
                onClick={() => setRouteRetry((v) => v + 1)}
              >
                Tentar carregar percursos
              </button>
            )}
          <VehicleList vehicles={visible} onSelect={onSelect} />
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
          ·{" "}
          {visual.mode === "density"
            ? "densidade de posições"
            : visual.mode === "mixed"
              ? "densidade e grupos"
              : "grupos por proximidade"}
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
          O centro dos grupos mostra a quantidade de posições; os anéis
          representam cores compartilhadas pelas linhas. Amplie para ver as
          posições individuais. Sentido 1: traço contínuo · sentido 2:
          tracejado. GPS antigo/desconhecido: ponto vazado e menor opacidade.
        </p>
        <p>
          SPTrans / Olho Vivo · coleta {collected} (Brasília). Ausência de GPS
          não comprova viagem não realizada.
        </p>
        {catalog?.status === "ready" && catalog.version ? (
          <p>
            Fonte GTFS: {catalog.source || "não informada"}.
            <br />
            Captura: {" "}
            {catalog.captured_at
              ? new Date(catalog.captured_at).toLocaleString("pt-BR", {
                  timeZone: "America/Sao_Paulo",
                })
              : "não informada"}
            {" "}(America/Sao_Paulo).
            <br />
            SHA-256: <code className="gtfs-hash">{catalog.version}</code>
            A data de captura não comprova vigência. Correspondências por
            letreiro e destino; códigos de sentido das fontes são independentes.
          </p>
        ) : (
          <p>Referência GTFS indisponível. Posições disponíveis continuam visíveis
            sem associações de área, cor ou percurso não comprovadas.</p>
        )}
      </details>
    </main>
  );
}
