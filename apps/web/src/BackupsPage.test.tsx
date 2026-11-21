import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import BackupsPage from "./BackupsPage";
import type { BackupStatus } from "./api/backups";

const data: BackupStatus = {
  checked_at: "2026-11-20T22:00:00Z", worker_active: false, heartbeat_at: null,
  heartbeat_timeout_seconds: 120, schedule: "Diariamente às 03:00 UTC", next_execution: null,
  overdue: true, last_success_at: "2026-11-18T22:00:00Z", attempts: [],
  points: [{ id: "old-point", completed_at: "2026-11-18T22:00:00Z", expired_at: null,
    manifest_sha256: "a".repeat(64), dump_sha256: "b".repeat(64), verified_at_creation: null }],
};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function unlock() {
  fireEvent.change(screen.getByLabelText("Chave de operação"), { target: { value: "private-test" } });
  fireEvent.click(screen.getByText("Consultar backups"));
}

it("não consulta sem chave; usa cabeçalho privado e encerra sem gravar credenciais", async () => {
  const calls: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: Request) => { calls.push(input); return Response.json(data); }));
  render(<BackupsPage />);
  expect(calls).toHaveLength(0);
  unlock();
  await screen.findByText("Rotina inativa ou sem sinal recente");
  expect(calls[0].headers.get("Authorization")).toBe("Bearer private-test");
  expect(calls[0].url).not.toContain("private-test");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  expect(screen.queryByText("private-test")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Encerrar acesso"));
  expect(screen.getByLabelText("Chave de operação")).toHaveValue("");
  expect(screen.queryByText("old-point")).not.toBeInTheDocument();
});

it("distingue histórico não revalidado, atraso e rotina inativa", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(data)));
  render(<BackupsPage />); unlock();
  expect(await screen.findByText(/registro histórico não revalidado/)).toBeInTheDocument();
  expect(screen.getByText(/Backup do período diário pendente/)).toBeInTheDocument();
  expect(screen.getByText("Sem previsão enquanto inativa")).toBeInTheDocument();
  expect(screen.queryByText(/Integridade verificada na criação:/)).not.toBeInTheDocument();
});

it("mostra rotina ativa, ponto verificado na criação e falha separada do sucesso anterior", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...data, worker_active: true,
    heartbeat_at: data.checked_at, next_execution: "2026-11-21T03:00:00Z", overdue: false,
    points: [{ ...data.points[0], verified_at_creation: data.checked_at }],
    attempts: [{ id: "failed-attempt", started_at: data.checked_at, finished_at: data.checked_at, status: "failed", backup_id: null }],
  })));
  render(<BackupsPage />); unlock();
  await screen.findByText("Sinal recente da rotina");
  expect(screen.getByText(/Integridade verificada na criação:/)).toBeInTheDocument();
  expect(screen.getByText(/A última tentativa falhou/)).toBeInTheDocument();
  expect(screen.getByText("Falhou ou foi interrompida")).toBeInTheDocument();
  expect(screen.queryByText("Concluída com sucesso")).not.toBeInTheDocument();
});

it("recupera falha de consulta sem tratar erro como catálogo vazio nem manter estado anterior", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(Response.json(data))
    .mockResolvedValueOnce(Response.json({ detail: "private-storage-url" }, { status: 503 }))
    .mockResolvedValueOnce(Response.json({ ...data, points: [] })));
  render(<BackupsPage />); unlock();
  await screen.findByText("old-point");
  fireEvent.click(screen.getByText("Atualizar backups"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível consultar os backups");
  expect(screen.queryByText("old-point")).not.toBeInTheDocument();
  expect(screen.queryByText("private-storage-url")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Atualizar backups"));
  expect(await screen.findByText("Nenhum ponto de recuperação registrado.")).toBeInTheDocument();
});

it("informa recusa de acesso sem expor resposta privada", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "secret" }, { status: 401 })));
  render(<BackupsPage />); unlock();
  expect(await screen.findByRole("alert")).toHaveTextContent("Acesso não autorizado");
  expect(screen.queryByText("secret")).not.toBeInTheDocument();
});
