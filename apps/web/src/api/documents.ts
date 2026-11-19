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
