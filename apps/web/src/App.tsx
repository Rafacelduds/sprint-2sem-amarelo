import { useEffect, useSyncExternalStore } from "react";
import MapPage from "./MapPage";
import DocumentsPage from "./DocumentsPage";
import "./Navigation.css";

function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}

export default function App() {
  const page = useSyncExternalStore(subscribe, () =>
    window.location.hash === "#acervo" ? "documents" : "map",
  );
  useEffect(() => {
    document.title = `ObservaÔnibus — ${page === "documents" ? "Acervo documental" : "Mapa ao vivo"}`;
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
        </div>
      </nav>
      {page === "documents" ? <DocumentsPage /> : <MapPage />}
    </>
  );
}
