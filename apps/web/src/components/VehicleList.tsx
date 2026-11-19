import { memo, useState } from "react";
import type { Vehicle } from "../api/positions";
const PAGE_SIZE = 100;
const formatter = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "medium",
  timeZone: "America/Sao_Paulo",
});
function VehicleList({
  vehicles,
  onSelect,
}: {
  vehicles: Vehicle[];
  onSelect?: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const lastPage = Math.max(0, Math.ceil(vehicles.length / PAGE_SIZE) - 1);
  const current = Math.min(page, lastPage);
  return (
    <details
      className="vehicle-list"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>Consultar posições em lista ({vehicles.length})</summary>
      {open && (
        <>
          <nav className="list-pagination" aria-label="Páginas de posições">
            <button
              disabled={current === 0}
              onClick={() => setPage(current - 1)}
            >
              Anterior
            </button>
            <span>
              Página {current + 1} de {lastPage + 1} · até 100 posições por
              página
            </span>
            <button
              disabled={current === lastPage}
              onClick={() => setPage(current + 1)}
            >
              Próxima
            </button>
          </nav>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Ônibus</th>
                  <th>Linha</th>
                  <th>Destino</th>
                  <th>Último GPS</th>
                  <th>Coordenadas</th>
                </tr>
              </thead>
              <tbody>
                {vehicles
                  .slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)
                  .map((bus) => (
                    <tr key={bus.id}>
                      <td>
                        {onSelect ? (
                          <button
                            className="vehicle-select"
                            aria-label={`Detalhes do ônibus ${bus.id}`}
                            onClick={() => onSelect(bus.id)}
                          >
                            {bus.id}
                          </button>
                        ) : (
                          bus.id
                        )}
                      </td>
                      <td>{bus.line}</td>
                      <td>{bus.destination}</td>
                      <td>
                        {bus.gps_at
                          ? formatter.format(new Date(bus.gps_at))
                          : "Não informado"}
                      </td>
                      <td>
                        {bus.latitude.toFixed(5)}, {bus.longitude.toFixed(5)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </details>
  );
}
export default memo(VehicleList);
