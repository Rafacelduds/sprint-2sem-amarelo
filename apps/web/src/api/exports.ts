import {
  catalogExportsRawGet,
  dictionaryExportsRawDictionaryGet,
  type ExportInfo,
} from "@amarelo/api-client";

export type { ExportInfo };
export const pageSize = 31;
const baseUrl = new URL(import.meta.env.VITE_API_URL ?? "/api", window.location.origin).href.replace(/\/$/, "");

export async function getExports(before: string | undefined, signal: AbortSignal) {
  const result = await catalogExportsRawGet({
    baseUrl, query: { before, limit: pageSize }, signal, cache: "no-store", throwOnError: true,
  });
  return result.data;
}

export async function getDictionary(signal: AbortSignal) {
  const result = await dictionaryExportsRawDictionaryGet({ baseUrl, signal, throwOnError: true });
  return result.data;
}

// O servidor verifica os bytes antes do envio. O ETag também fixa a revisão
// escolhida: uma republicação concorrente exige atualizar o catálogo.
export async function downloadExport(item: ExportInfo, signal: AbortSignal) {
  const response = await fetch(`${baseUrl}/exports/raw/${encodeURIComponent(item.dia)}/download`, {
    signal, cache: "no-store",
  });
  if (!response.ok) throw new Error("Arquivo indisponível. Tente novamente ou atualize o catálogo.");
  if (response.headers.get("ETag") !== `"${item.sha256}"`) {
    throw new Error("A revisão do arquivo mudou. Atualize o catálogo antes de baixar.");
  }
  if (response.headers.get("Content-Type")?.split(";")[0] !== "application/vnd.apache.parquet") {
    throw new Error("O serviço não retornou um arquivo Parquet. Tente novamente.");
  }
  const blob = await response.blob();
  if (blob.size !== item.bytes) throw new Error("O arquivo recebido está incompleto. Tente novamente.");
  return blob;
}

export function saveExport(blob: Blob, day: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `brutos-${day}.parquet`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Dar tempo ao navegador para iniciar o salvamento antes de liberar os bytes.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
