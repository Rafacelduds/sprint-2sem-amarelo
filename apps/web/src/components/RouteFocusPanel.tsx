import { useEffect, useRef } from "react";
export default function RouteFocusPanel({
  available,
  overview = false,
  focus,
  destinations = [],
  candidates,
  scrollRequest,
  onChoose,
  onAll,
  onDismiss,
}: {
  available: number;
  overview?: boolean;
  focus: string | null;
  destinations?: string[];
  candidates: string[];
  scrollRequest: number;
  onChoose: (label: string) => void;
  onAll: () => void;
  onDismiss: () => void;
}) {
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    if (scrollRequest) {
      root.current?.scrollIntoView?.({ block: "nearest" });
      root.current?.focus({ preventScroll: true });
    }
  }, [scrollRequest]);
  if (!available) return null;
  return (
    <section
      ref={root}
      tabIndex={-1}
      className="route-focus-panel"
      aria-label="Destaque dos percursos"
    >
      <div className="route-focus-heading">
        <strong role="status">
          {focus
            ? `Em foco: ${focus}`
            : overview
              ? `Percursos das áreas · ${available} linhas`
              : "Todos os percursos em destaque"}
        </strong>
        {(focus || overview) && <button onClick={onAll}>Destacar todas</button>}
      </div>
      {focus && destinations.length > 0 && <p>{destinations.join(" · ")}</p>}
      <p>Clique no percurso ou no número da linha para destacar.</p>
      {candidates.length > 1 && (
        <div className="route-candidates">
          <strong>Linhas neste trecho</strong>
          <p>Qual linha você quer destacar?</p>
          <div>
            {candidates.map((label) => (
              <button
                key={label}
                onClick={() => onChoose(label)}
                aria-label={`Escolher linha ${label}`}
              >
                {label}
              </button>
            ))}
          </div>
          <button className="dismiss-routes" onClick={onDismiss}>
            Fechar escolha
          </button>
        </div>
      )}
    </section>
  );
}
