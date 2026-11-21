import { useEffect, useState } from "react";
import { coverageCollectionCoverageGet, type CoverageView } from "@amarelo/api-client";
import "./CollectionCoverage.css";

export default function CollectionCoverage() {
  const [data, setData] = useState<CoverageView | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    async function load() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10_000);
      try {
        const baseUrl = new URL(import.meta.env.VITE_API_URL ?? "/api", window.location.origin).href.replace(/\/$/, "");
        const result = await coverageCollectionCoverageGet({ baseUrl, signal: controller.signal, cache: "no-store" });
        if (!result.response.ok || !result.data || !["complete", "partial", "unknown"].includes(result.data.status) || !Array.isArray(result.data.failed_garage_companies)) throw new Error("unavailable");
        if (active) { setData(result.data); setFailed(false); }
      } catch { if (active) { setData(null); setFailed(true); } }
      finally { clearTimeout(timeout); if (active) timer = setTimeout(() => void load(), 30_000); }
    }
    void load();
    return () => { active = false; clearTimeout(timer); controller?.abort(); };
  }, []);
  const time = data?.cycle_at ? new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "medium" }).format(new Date(data.cycle_at)) : null;
  return <section className="collection-coverage" role="status" aria-label="Cobertura da coleta histórica">
    <strong>{failed ? "Cobertura não pôde ser consultada" : !data ? "Consultando cobertura da coleta…" : data.status === "unknown" ? "Cobertura histórica sem informação" : data.status === "partial" ? "Coleta histórica com cobertura parcial" : "Último ciclo histórico concluído"}</strong>
    {data && time && <p>Ciclo de {time} (São Paulo). {data.stale ? "Registro sem atualização recente; a situação atual é desconhecida." : "Situação do último ciclo concluído."}</p>}
    {data?.failed_garage_companies.length ? <p>Não foi possível ler as garagens das empresas {data.failed_garage_companies.join(", ")} nesse ciclo. Essa parte dos dados pode estar ausente.</p> : null}
    {data?.status === "partial" && <p>Os dados que puderam ser coletados foram preservados. Isso não significa ausência de ônibus ou viagens canceladas.</p>}
    {(failed || data?.status === "unknown") && <p>Não há evidência suficiente para afirmar cobertura completa.</p>}
    <p>Este aviso trata da coleta histórica; o mapa ao vivo usa uma consulta separada. Não certifica a cobertura de outros períodos. <a href="#confiabilidade">Consultar confiabilidade por dia</a>.</p>
  </section>;
}
