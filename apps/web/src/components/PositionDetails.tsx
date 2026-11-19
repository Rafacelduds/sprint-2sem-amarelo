import { useEffect, useRef, useState } from "react";
import type { Vehicle } from "../api/positions";
import { gpsQuality, UNKNOWN_COLOR, type LineStyle } from "../network";
import {
  clusterPage,
  CLUSTER_PAGE_SIZE,
  type GroupSelection,
} from "../clusters";
const formatter = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "medium",
  timeZone: "America/Sao_Paulo",
});
function date(value: string | null) {
  return value && Number.isFinite(Date.parse(value))
    ? formatter.format(new Date(value))
    : "Não informado";
}
export default function PositionDetails({
  selectedId,
  vehicle,
  group,
  styles,
  collectedAt,
  now,
  onSelect,
  onClose,
}: {
  selectedId: string | null;
  vehicle: Vehicle | null;
  group: GroupSelection | null;
  styles: Map<number, LineStyle>;
  collectedAt: string | null;
  now: number;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const [pagination, setPagination] = useState<{
    group: GroupSelection;
    page: number;
  } | null>(null);
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    if (selectedId || group)
      root.current?.scrollIntoView?.({ block: "nearest" });
  }, [selectedId, group]);
  if (!selectedId && !group) return null;
  const page = pagination?.group === group ? pagination.page : 0;
  const style = vehicle ? styles.get(vehicle.line_id) : undefined;
  const quality = vehicle ? gpsQuality(vehicle, now) : null;
  return (
    <section
      ref={root}
      className="position-details"
      aria-label="Detalhes da seleção"
    >
      <div className="position-heading">
        <strong>{group ? "Ônibus neste local" : "Ônibus selecionado"}</strong>
        <button onClick={onClose} aria-label="Fechar detalhes">
          ×
        </button>
      </div>
      <details open key={group ? `group:${group.id}` : selectedId}>
        <summary>
          {group
            ? `${group.total.toLocaleString("pt-BR")} posições coincidentes`
            : vehicle
              ? `${vehicle.line} · Ônibus ${vehicle.id}`
              : "Posição indisponível"}
        </summary>
        {group ? (
          <>
            <ul className="coincident-list">
              {clusterPage(group.index, group.id, page).map((bus) => (
                <li key={bus.id}>
                  <button onClick={() => onSelect(bus.id)}>
                    <strong>
                      {bus.line} · Ônibus {bus.id}
                    </strong>
                    <span>
                      Sentido {bus.direction} ·{" "}
                      {bus.destination || "Destino não informado"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <nav className="group-pagination" aria-label="Páginas do grupo">
              <button
                disabled={page === 0}
                onClick={() => setPagination({ group, page: page - 1 })}
              >
                Anterior
              </button>
              <span aria-live="polite">
                {page + 1} / {Math.ceil(group.total / CLUSTER_PAGE_SIZE)}
              </span>
              <button
                disabled={(page + 1) * CLUSTER_PAGE_SIZE >= group.total}
                onClick={() => setPagination({ group, page: page + 1 })}
              >
                Próxima
              </button>
            </nav>
          </>
        ) : vehicle ? (
          <dl>
            <dt>Linha</dt>
            <dd>
              <span
                className="detail-color"
                style={{ background: style?.color ?? UNKNOWN_COLOR }}
              />
              {vehicle.line}
            </dd>
            <dt>Destino</dt>
            <dd>{vehicle.destination || "Não informado"}</dd>
            <dt>Sentido</dt>
            <dd>{vehicle.direction}</dd>
            <dt>Área</dt>
            <dd>{style?.area ? `Área ${style.area}` : "Não confirmada"}</dd>
            <dt>Acessível</dt>
            <dd>
              {vehicle.accessible == null
                ? "Não informado"
                : vehicle.accessible
                  ? "Sim"
                  : "Não"}
            </dd>
            <dt>Último GPS</dt>
            <dd>
              {date(vehicle.gps_at)} ·{" "}
              {quality === "recent"
                ? "Recente"
                : quality === "old"
                  ? "Antigo"
                  : "Horário desconhecido"}
            </dd>
            <dt>Coordenadas</dt>
            <dd>
              {vehicle.latitude.toFixed(5)}, {vehicle.longitude.toFixed(5)}
            </dd>
            <dt>Coleta</dt>
            <dd>{date(collectedAt)}</dd>
          </dl>
        ) : (
          <p role="status">
            A posição selecionada deixou de estar disponível ou está fora dos
            filtros.
          </p>
        )}
      </details>
    </section>
  );
}
