import { memo, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { HeatLayer } from "leaflet.heat";
import { heatAppearance, type Visualization } from "../visualization";
import type { Vehicle } from "../api/positions";
import type { RouteCollection } from "../api/network";
import {
  availableRouteLabels,
  projectRoutes,
  routesNearPoint,
  routePaint,
  casingColor,
} from "../routeFocus";
import {
  gpsQuality,
  UNKNOWN_COLOR,
  type Bounds,
  type LineStyle,
} from "../network";
import {
  createBusIndex,
  clusterDiameter,
  isCluster,
  MAP_MAX_ZOOM,
  groupGradient,
  type ColorCounts,
  type GroupSelection,
} from "../clusters";
import "leaflet/dist/leaflet.css";

// The plugin supports Leaflet 1.9 at runtime; its bundled Layer types target 2.x.
type CompatibleHeatLayer = L.Layer &
  Pick<HeatLayer, "setLatLngs" | "setOptions">;
const CENTER: L.LatLngExpression = [-23.5505, -46.6333];
type Entry = {
  marker: L.Marker | L.CircleMarker;
  count: number;
  signature?: string;
};
function groupIcon(count: number, colors: ColorCounts, visual: Visualization) {
  const diameter =
    clusterDiameter(count, visual.groupSizing) * visual.groupScale;
  const label = document.createElement("span");
  label.textContent = String(count);
  if (count >= 10000) label.style.fontSize = "9px";
  const ring = document.createElement("div");
  ring.className = "cluster-ring";
  ring.style.background = groupGradient(colors, visual.composition);
  ring.append(label);
  return L.divIcon({
    className: "bus-cluster",
    html: ring,
    iconSize: [diameter, diameter],
    iconAnchor: [diameter / 2, diameter / 2],
  });
}

function BusMap({
  vehicles,
  visual,
  selected,
  onSelect,
  onGroup,
  styles,
  routes,
  routeFocus,
  areaRoutes = false,
  routeOverview = false,
  onRoutePick,
  fitRequest,
  onBounds,
  now,
}: {
  vehicles: Vehicle[];
  visual: Visualization;
  selected: Vehicle | null;
  onSelect: (id: string) => void;
  onGroup: (group: GroupSelection | null) => void;
  styles: Map<number, LineStyle>;
  routes: RouteCollection[];
  routeFocus: string | null;
  areaRoutes?: boolean;
  routeOverview?: boolean;
  onRoutePick: (labels: string[]) => void;
  fitRequest: number;
  onBounds: (bounds: Bounds) => void;
  now: number;
}) {
  const hasRoutes = useMemo(
    () => availableRouteLabels(routes).size > 0,
    [routes],
  );
  const index = useMemo(
    () => createBusIndex(vehicles, styles),
    [vehicles, styles],
  );
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const entries = useRef(new Map<string, Entry>());
  const fitVersion = useRef(fitRequest);
  const routeLayer = useRef<L.LayerGroup | null>(null);
  const vehicleRenderer = useRef<L.Canvas | null>(null);
  const [tileError, setTileError] = useState(false);
  const heat = useRef<CompatibleHeatLayer | null>(null);
  const focusLayer = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const instance = L.map(container.current, {
      preferCanvas: true,
      zoomControl: false,
      maxZoom: MAP_MAX_ZOOM,
    }).setView(CENTER, 12);
    instance.createPane("density").style.zIndex = "340";
    instance.getPane("density")!.style.pointerEvents = "none";
    instance.createPane("selectedVehicle").style.zIndex = "470";
    instance.getPane("selectedVehicle")!.style.pointerEvents = "none";
    instance.createPane("plannedRoutes").style.zIndex = "350";
    instance.getPane("plannedRoutes")!.style.pointerEvents = "none";
    instance.createPane("vehiclePositions").style.zIndex = "450";
    instance.createPane("vehicleClusters").style.zIndex = "460";
    vehicleRenderer.current = L.canvas({
      pane: "vehiclePositions",
      tolerance: 7,
    });
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
    focusLayer.current = L.layerGroup().addTo(instance);
    heat.current = new HeatLayer([], {
      pane: "density",
      radius: 25,
      blur: 15,
      minOpacity: 0.08,
      max: 4,
      maxZoom: 15,
      gradient: {
        0.1: "#e0c9f0",
        0.45: "#b07acd",
        0.75: "#7c3fa0",
        1: "#49126d",
      },
    }) as unknown as CompatibleHeatLayer;
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
      heat.current = null;
      focusLayer.current = null;
      vehicleRenderer.current = null;
    };
  }, [onBounds]);

  useEffect(() => {
    onGroup(null);
  }, [index, onGroup]);

  useEffect(() => {
    const instance = map.current;
    const layer = heat.current;
    if (!instance || !layer) return;
    if (visual.mode === "clusters") {
      layer.remove();
      layer.setLatLngs([]);
      return;
    }
    const appearance = heatAppearance(visual.heatIntensity, visual.mode);
    instance.getPane("density")!.style.opacity = String(
      appearance.opacity * (hasRoutes ? 0.5 : 1),
    );
    layer.setOptions({ max: appearance.max });
    layer.setLatLngs(vehicles.map((bus) => [bus.latitude, bus.longitude, 1]));
    if (!instance.hasLayer(layer)) layer.addTo(instance);
  }, [vehicles, visual.mode, visual.heatIntensity, hasRoutes]);

  useEffect(() => {
    const layer = focusLayer.current;
    if (!layer) return;
    layer.clearLayers();
    if (selected) {
      L.circleMarker([selected.latitude, selected.longitude], {
        radius: visual.busDiameter / 2 + 4,
        weight: 3,
        color: "#172b31",
        fill: false,
        pane: "selectedVehicle",
        interactive: false,
      }).addTo(layer);
      L.circleMarker([selected.latitude, selected.longitude], {
        radius: visual.busDiameter / 2,
        weight: 1,
        color: "#fff",
        fillColor: styles.get(selected.line_id)?.color ?? UNKNOWN_COLOR,
        fillOpacity: gpsQuality(selected, now) === "recent" ? 0.9 : 0.15,
        pane: "selectedVehicle",
        interactive: false,
      }).addTo(layer);
    }
  }, [selected, visual.busDiameter, styles, now]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const pool = entries.current;
    const redraw = () => {
      const bounds = instance.getBounds().pad(0.05);
      const zoom = Math.min(MAP_MAX_ZOOM, Math.floor(instance.getZoom()));
      const points =
        visual.mode === "density"
          ? []
          : index.getClusters(
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
          const colors = point.properties.colors;
          const signature = JSON.stringify([
            colors,
            visual.composition,
            visual.groupScale,
            visual.groupSizing,
            count,
          ]);
          if (!entry) {
            const marker = L.marker(latlng, {
              icon: groupIcon(count, colors, visual),
              pane: "vehicleClusters",
              title: `${count} ônibus agrupados. Ativar para explorar.`,
              keyboard: true,
              bubblingMouseEvents: false,
            }).addTo(instance);
            entry = { marker, count, signature };
            pool.set(key, entry);
          } else {
            if (!entry.marker.getLatLng().equals(latlng))
              entry.marker.setLatLng(latlng);
            if (
              entry.signature !== signature &&
              entry.marker instanceof L.Marker
            )
              entry.marker.setIcon(groupIcon(count, colors, visual));
            entry.count = count;
            entry.signature = signature;
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
              onGroup({ index, id, total: count });
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
            renderer: vehicleRenderer.current!,
            radius: visual.busDiameter / 2,
            weight: old ? 1.5 : 1,
            color: old ? color : "#fff",
            fillColor: color,
            fillOpacity: old ? 0.15 : 0.9,
            dashArray: old ? "2 2" : undefined,
            pane: "vehiclePositions",
            bubblingMouseEvents: false,
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
          entry.marker.off("click").on("click", () => onSelect(bus.id));
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
  }, [index, visual, styles, now, onSelect, onGroup]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    instance.getPane("tilePane")!.style.opacity = hasRoutes ? "0.72" : "1";
    instance.getPane("vehiclePositions")!.style.opacity = hasRoutes
      ? "0.6"
      : "1";
    instance.getPane("vehicleClusters")!.style.opacity = hasRoutes
      ? "0.55"
      : "1";
  }, [hasRoutes]);

  useEffect(() => {
    const instance = map.current;
    const layer = routeLayer.current;
    if (!layer || !instance) return;
    layer.clearLayers();
    const features = routes
      .flatMap((route) => route.features)
      .sort(
        (a, b) =>
          Number(a.properties.label === routeFocus) -
          Number(b.properties.label === routeFocus),
      );
    for (const feature of features) {
      const color =
        styles.get(feature.properties.line_id)?.color ?? UNKNOWN_COLOR;
      const paint = routePaint(
        feature.properties.label,
        routeFocus,
        areaRoutes,
        routeOverview,
      );
      for (const segment of feature.geometry.coordinates) {
        const path = segment.map(([lon, lat]) => L.latLng(lat, lon));
        const options = {
          pane: "plannedRoutes",
          interactive: false,
          dashArray: feature.properties.direction === 2 ? "7 6" : undefined,
        };
        if (paint.casing)
          L.polyline(path, {
            ...options,
            color: casingColor(color),
            weight: paint.weight + 2,
            opacity: 0.85,
          }).addTo(layer);
        L.polyline(path, {
          ...options,
          color,
          weight: paint.weight,
          opacity: paint.opacity,
        }).addTo(layer);
      }
    }
  }, [routes, styles, routeFocus, areaRoutes, routeOverview]);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !hasRoutes) return;
    const project = () =>
      projectRoutes(
        routes,
        ([lon, lat]) => instance.latLngToContainerPoint([lat, lon]),
        instance.getSize(),
        (points) => L.LineUtil.simplify(points as L.Point[], 1.5),
      );
    let segments = project();
    const update = () => {
      segments = project();
    };
    const click = (event: L.LeafletMouseEvent) => {
      const labels = routesNearPoint(segments, event.containerPoint);
      if (labels.length) onRoutePick(labels);
    };
    instance.on("moveend zoomend resize", update);
    instance.on("click", click);
    return () => {
      instance.off("moveend zoomend resize", update);
      instance.off("click", click);
    };
  }, [routes, hasRoutes, onRoutePick]);

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
