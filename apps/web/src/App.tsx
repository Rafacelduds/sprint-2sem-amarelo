import { useEffect, useSyncExternalStore } from "react";
import MapPage from "./MapPage";
import DocumentsPage from "./DocumentsPage";
import SchedulesPage from "./SchedulesPage";
import ReliabilityPage from "./ReliabilityPage";
import ExportsPage from "./ExportsPage";
import CollectionPage from "./CollectionPage";
import BackupsPage from "./BackupsPage";
import "./Navigation.css";

function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}

export default function App() {
  const page = useSyncExternalStore(subscribe, () =>
    window.location.hash === "#coleta" ? "collection"
      : window.location.hash === "#backups" ? "backups"
      : window.location.hash === "#dados-brutos" ? "exports"
      : window.location.hash === "#programacao" ? "schedules"
      : window.location.hash === "#confiabilidade" ? "reliability"
      : window.location.hash === "#acervo" ? "documents" : "map",
  );
  useEffect(() => {
    document.title = `ObservaÔnibus — ${page === "collection" ? "Coleta persistida" : page === "backups" ? "Backups e recuperação" : page === "exports" ? "Dados brutos em Parquet" : page === "schedules" ? "Programação das linhas" : page === "reliability" ? "Confiabilidade da coleta" : page === "documents" ? "Acervo documental" : "Mapa ao vivo"}`;
  }, [page]);
  return (
    <div className={page === "map" ? "app-shell app-shell-map" : "app-shell"}>
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
          <a href="#coleta" aria-current={page === "collection" ? "page" : undefined}>Coleta · equipe</a>
          <a href="#backups" aria-current={page === "backups" ? "page" : undefined}>Backups · equipe</a>
        </div>
      </nav>
      {page === "collection" ? <CollectionPage /> : page === "backups" ? <BackupsPage /> : page === "exports" ? <ExportsPage /> : page === "schedules" ? <SchedulesPage /> : page === "reliability" ? <ReliabilityPage /> : page === "documents" ? <DocumentsPage /> : <MapPage />}
    </div>
  );
}
