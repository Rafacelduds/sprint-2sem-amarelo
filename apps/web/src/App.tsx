import { useEffect, useSyncExternalStore } from "react";
import MapPage from "./MapPage";
import DocumentsPage from "./DocumentsPage";
import SchedulesPage from "./SchedulesPage";
import ReliabilityPage from "./ReliabilityPage";
import ExportsPage from "./ExportsPage";
import "./Navigation.css";

function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}

export default function App() {
  const page = useSyncExternalStore(subscribe, () =>
    window.location.hash === "#dados-brutos" ? "exports"
      : window.location.hash === "#programacao" ? "schedules"
      : window.location.hash === "#confiabilidade" ? "reliability"
      : window.location.hash === "#acervo" ? "documents" : "map",
  );
  useEffect(() => {
    document.title = `ObservaÔnibus — ${page === "exports" ? "Dados brutos em Parquet" : page === "schedules" ? "Programação das linhas" : page === "reliability" ? "Confiabilidade da coleta" : page === "documents" ? "Acervo documental" : "Mapa ao vivo"}`;
  }, [page]);
  return (
    <>
      <nav className="site-navigation" aria-label="Navegação principal">
        <span>
          ObservaÔnibus <small>São Paulo</small>
        </span>
        <div>
          <a href="#mapa" aria-current={page === "map" ? "page" : undefined}>
            Mapa ao vivo
          </a>
          <a
            href="#acervo"
            aria-current={page === "documents" ? "page" : undefined}
          >
            Acervo documental
          </a>
          <a href="#programacao" aria-current={page === "schedules" ? "page" : undefined}>Programação</a>
          <a href="#confiabilidade" aria-current={page === "reliability" ? "page" : undefined}>
            Confiabilidade
          </a>
          <a href="#dados-brutos" aria-current={page === "exports" ? "page" : undefined}>Dados brutos</a>
        </div>
      </nav>
      {page === "exports" ? <ExportsPage /> : page === "schedules" ? <SchedulesPage /> : page === "reliability" ? <ReliabilityPage /> : page === "documents" ? <DocumentsPage /> : <MapPage />}
    </>
  );
}
