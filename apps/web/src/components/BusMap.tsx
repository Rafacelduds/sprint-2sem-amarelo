import { memo, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import type { Vehicle } from "../api/positions";
import type { RouteCollection } from "../api/network";
import {
  gpsQuality,
  UNKNOWN_COLOR,
  type Bounds,
  type LineStyle,
  type Selection,
} from "../network";
import {
  createBusIndex,
  clusterDiameter,
  clusterPage,
  isCluster,
  MAP_MAX_ZOOM,
  CLUSTER_PAGE_SIZE,
  type BusIndex,
} from "../clusters";
import "leaflet/dist/leaflet.css";

const CENTER: L.LatLngExpression = [-23.5505, -46.6333];
const gpsFormatter = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "medium",
  timeZone: "America/Sao_Paulo",
});
type Entry = { marker: L.Marker | L.CircleMarker; count: number };

function popup(bus: Vehicle, now: number) {
  const detail = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = `${bus.line} · Ônibus ${bus.id}`;
  detail.append(title);
  for (const text of [
    `Destino: ${bus.destination || "Não informado"}`,
    `Sentido ${bus.direction}`,
    `GPS: ${bus.gps_at ? gpsFormatter.format(new Date(bus.gps_at)) : "não informado"}`,
    gpsQuality(bus, now) !== "recent"
      ? "GPS antigo ou horário desconhecido"
      : "GPS recente",
    `Acessível: ${bus.accessible == null ? "não informado" : bus.accessible ? "sim" : "não"}`,
  ]) {
    const p = document.createElement("p");
    p.textContent = text;
    detail.append(p);
  }
  return detail;
}

function groupPopup(index: BusIndex, id: number, total: number) {
  const root = document.createElement("section");
  root.className = "cluster-popup";
  root.setAttribute("aria-label", "Veículos coincidentes");
  const title = document.createElement("strong");
  title.textContent = `${total.toLocaleString("pt-BR")} ônibus neste local`;
  const list = document.createElement("ul");
  const nav = document.createElement("nav");
  nav.setAttribute("aria-label", "Páginas do grupo");
  const previous = document.createElement("button");
  previous.textContent = "Anterior";
  const next = document.createElement("button");
  next.textContent = "Próxima";
  const status = document.createElement("span");
  status.setAttribute("aria-live", "polite");
  let page = 0;
  const last = Math.ceil(total / CLUSTER_PAGE_SIZE) - 1;
  const render = () => {
    list.replaceChildren();
    for (const bus of clusterPage(index, id, page)) {
      const item = document.createElement("li");
      item.textContent = `${bus.line} · Ônibus ${bus.id} · sentido ${bus.direction} · ${bus.destination || "Destino não informado"}`;
      list.append(item);
    }
    previous.disabled = page === 0;
    next.disabled = page === last;
    status.textContent = `${page + 1} / ${last + 1}`;
  };
  previous.onclick = () => {
    page--;
    render();
  };
  next.onclick = () => {
    page++;
    render();
  };
  nav.append(previous, status, next);
  root.append(title, list, nav);
  render();
  return root;
}
function groupIcon(count: number) {
  const diameter = clusterDiameter(count);
  const label = document.createElement("span");
  label.textContent = String(count);
  if (count >= 10000) label.style.fontSize = "8px";
  return L.divIcon({
    className: "bus-cluster",
    html: label,
    iconSize: [diameter, diameter],
    iconAnchor: [diameter / 2, diameter / 2],
  });
}

function BusMap({
  vehicles,
  selection,
  styles,
  routes,
  fitRequest,
  onBounds,
  now,
}: {
  vehicles: Vehicle[];
  selection: Selection;
  styles: Map<number, LineStyle>;
  routes: RouteCollection[];
  fitRequest: number;
  onBounds: (bounds: Bounds) => void;
  now: number;
}) {
  const index = useMemo(() => createBusIndex(vehicles), [vehicles]);
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const entries = useRef(new Map<string, Entry>());
  const fitVersion = useRef(fitRequest);
  const routeLayer = useRef<L.LayerGroup | null>(null);
  const [tileError, setTileError] = useState(false);

  useEffect(() => {
    if (!container.current) return;
    const instance = L.map(container.current, {
      preferCanvas: true,
      zoomControl: false,
      maxZoom: MAP_MAX_ZOOM,
    }).setView(CENTER, 12);
    instance.createPane("plannedRoutes").style.zIndex = "350";
    instance.getPane("plannedRoutes")!.style.pointerEvents = "none";
    instance.createPane("vehiclePositions").style.zIndex = "450";
    instance.createPane("vehicleClusters").style.zIndex = "460";
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    })
      .on("tileerror", () => setTileError(true))
      .addTo(instance);
    L.control.zoom({ position: "topright" }).addTo(instance);
    map.current = instance;
    routeLayer.current = L.layerGroup().addTo(instance);
    const report = () => {
      const bounds = instance.getBounds();
      onBounds({
        north: bounds.getNorth(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        west: bounds.getWest(),
      });
    };
    report();
    instance.on("moveend", report);
    const pool = entries.current;
    const observer = new ResizeObserver(() => instance.invalidateSize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      instance.remove();
      pool.clear();
      map.current = null;
    };
  }, [onBounds]);

  useEffect(() => {
    map.current?.closePopup();
  }, [index]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const pool = entries.current;
    const redraw = () => {
      const bounds = instance.getBounds().pad(0.05);
      const zoom = Math.min(MAP_MAX_ZOOM, Math.floor(instance.getZoom()));
      const points = index.getClusters(
        [
          bounds.getWest(),
          bounds.getSouth(),
          bounds.getEast(),
          bounds.getNorth(),
        ],
        zoom,
      );
      const keys = new Set<string>();
      for (const point of points) {
        const grouped = isCluster(point);
        const key = grouped
          ? `cluster:${point.properties.cluster_id}`
          : `bus:${point.properties.bus.id}`;
        keys.add(key);
        const [lon, lat] = point.geometry.coordinates;
        const latlng = L.latLng(lat, lon);
        let entry = pool.get(key);
        if (grouped) {
          const count = point.properties.point_count;
          if (!entry) {
            const marker = L.marker(latlng, {
              icon: groupIcon(count),
              pane: "vehicleClusters",
              title: `${count} ônibus agrupados. Ativar para explorar.`,
              keyboard: true,
            }).addTo(instance);
            entry = { marker, count };
            pool.set(key, entry);
          } else {
            if (!entry.marker.getLatLng().equals(latlng))
              entry.marker.setLatLng(latlng);
            if (entry.count !== count && entry.marker instanceof L.Marker)
              entry.marker.setIcon(groupIcon(count));
            entry.count = count;
          }
          entry.marker
            .getElement()
            ?.setAttribute(
              "aria-label",
              `${count} ônibus agrupados. Ativar para explorar.`,
            );
          const id = point.properties.cluster_id;
          entry.marker.off("click").on("click", () => {
            if (instance.getZoom() >= MAP_MAX_ZOOM) {
              entry!.marker
                .bindPopup(() => groupPopup(index, id, count), {
                  maxWidth: 320,
                })
                .openPopup();
            } else {
              instance.setView(
                latlng,
                Math.min(
                  MAP_MAX_ZOOM,
                  Math.max(
                    instance.getZoom() + 1,
                    index.getClusterExpansionZoom(id),
                  ),
                ),
              );
            }
          });
        } else {
          const bus = point.properties.bus;
          const old = gpsQuality(bus, now) !== "recent";
          const color = styles.get(bus.line_id)?.color ?? UNKNOWN_COLOR;
          const style = {
            radius: selection[bus.line] !== undefined ? 4.5 : 3,
            weight: old ? 1.5 : 1,
            color: old ? color : "#fff",
            fillColor: color,
            fillOpacity: old ? 0.15 : 0.9,
            dashArray: old ? "2 2" : undefined,
            pane: "vehiclePositions",
          };
          if (!entry) {
            entry = {
              marker: L.circleMarker(latlng, style).addTo(instance),
              count: 1,
            };
            pool.set(key, entry);
          } else {
            if (!entry.marker.getLatLng().equals(latlng))
              entry.marker.setLatLng(latlng);
            (entry.marker as L.CircleMarker).setStyle(style);
          }
          entry.marker
            .off("click")
            .on("click", () =>
              entry!.marker.bindPopup(() => popup(bus, now)).openPopup(),
            );
        }
      }
      for (const [key, entry] of pool)
        if (!keys.has(key)) {
          entry.marker.remove();
          pool.delete(key);
        }
    };
    redraw();
    instance.on("moveend zoomend", redraw);
    return () => {
      instance.off("moveend zoomend", redraw);
    };
  }, [index, selection, styles, now]);

  useEffect(() => {
    const layer = routeLayer.current;
    if (!layer) return;
    layer.clearLayers();
    for (const route of routes)
      for (const feature of route.features) {
        const color =
          styles.get(feature.properties.line_id)?.color ?? UNKNOWN_COLOR;
        for (const segment of feature.geometry.coordinates) {
          L.polyline(
            segment.map(([lon, lat]) => L.latLng(lat, lon)),
            {
              color,
              weight: 3,
              opacity: 0.4,
              pane: "plannedRoutes",
              dashArray: feature.properties.direction === 2 ? "7 6" : undefined,
              interactive: false,
            },
          ).addTo(layer);
        }
      }
  }, [routes, styles]);

  useEffect(() => {
    if (fitVersion.current === fitRequest) return;
    fitVersion.current = fitRequest;
    const points = vehicles.map((bus) => L.latLng(bus.latitude, bus.longitude));
    for (const route of routes)
      for (const feature of route.features)
        for (const segment of feature.geometry.coordinates) {
          points.push(...segment.map(([lon, lat]) => L.latLng(lat, lon)));
        }
    if (points.length)
      map.current?.fitBounds(L.latLngBounds(points), {
        paddingTopLeft: [window.innerWidth > 700 ? 400 : 25, 45],
        paddingBottomRight: [
          45,
          window.innerWidth > 700
            ? 45
            : Math.round(window.innerHeight * 0.44 + 65),
        ],
        maxZoom: 15,
      });
  }, [fitRequest, vehicles, routes]);

  return (
    <>
      <div
        ref={container}
        className="bus-map"
        role="region"
        aria-label="Mapa de posições dos ônibus em São Paulo"
      />
      {tileError && (
        <p className="tile-warning" role="status">
          O mapa de ruas está indisponível. Consulte as posições na lista.
        </p>
      )}
      <button
        className="map-reset"
        onClick={() => map.current?.setView(CENTER, 12)}
      >
        Centralizar São Paulo
      </button>
    </>
  );
}
export default memo(BusMap);
