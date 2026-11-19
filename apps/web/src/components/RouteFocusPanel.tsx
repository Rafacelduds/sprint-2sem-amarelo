import { useEffect, useRef } from "react";
export default function RouteFocusPanel({
  available,
  focus,
  candidates,
  scrollRequest,
  onChoose,
  onAll,
  onDismiss,
}: {
  available: number;
  focus: string | null;
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
          {focus ? `Em foco: ${focus}` : "Todos os percursos em destaque"}
        </strong>
        {focus && <button onClick={onAll}>Destacar todas</button>}
      </div>
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
