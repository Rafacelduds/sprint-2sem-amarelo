import {
  searchDocumentsDocumentsGet,
  type DocumentView,
} from "@amarelo/api-client";

export type { DocumentPage, DocumentView } from "@amarelo/api-client";
export interface DocumentFilters {
  type: DocumentView["document_type"] | "";
  dateField: "document_date" | "catalogued_at";
  from: string;
  to: string;
}

const base = new URL(
  import.meta.env.VITE_API_URL ?? "/api",
  window.location.origin,
).href.replace(/\/$/, "");
export const pageSize = 20;

export async function getDocuments(
  filters: DocumentFilters,
  offset: number,
  signal: AbortSignal,
) {
  const result = await searchDocumentsDocumentsGet({
    baseUrl: base,
    query: {
      document_type: filters.type || undefined,
      date_field: filters.dateField,
      date_from: filters.from || undefined,
      date_to: filters.to || undefined,
      limit: pageSize,
      offset,
    },
    signal,
    cache: "no-store",
    throwOnError: true,
  });
  return result.data;
}

export function documentPdfUrl(id: string) {
  return `${base}/documents/${encodeURIComponent(id)}/pdf`;
}

export async function getDocumentPdf(document: DocumentView, signal: AbortSignal) {
  const response = await fetch(documentPdfUrl(document.id), { signal, cache: "no-store" })
    .catch(() => { throw new Error("Não foi possível receber o PDF. Tente novamente."); });
  if (!response.ok) throw new Error("PDF indisponível. Tente novamente em instantes.");
  if (response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== "application/pdf") {
    throw new Error("O serviço não retornou um PDF. Tente novamente em instantes.");
  }
  const blob = await response.blob()
    .catch(() => { throw new Error("A transferência do PDF foi interrompida. Tente novamente."); });
  if (blob.size !== document.size) throw new Error("PDF recebido incompleto. Tente novamente.");
  // A API verifica o SHA-256 da versão original antes de enviar os bytes.
  return blob;
}
