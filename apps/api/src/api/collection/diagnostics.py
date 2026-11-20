"""Resumo operacional: não incluir respostas, URLs ou credenciais nos alertas."""

import re

from pydantic import BaseModel, Field


class CycleDiagnostics(BaseModel):
    status: str
    rounds: int | None = Field(default=None, ge=0, le=6)
    road_saved: bool | None = None
    garages_saved: int | None = Field(default=None, ge=0)
    companies_discovered: bool | None = None
    failures: dict[str, str] = Field(default_factory=lambda: dict[str, str]())
    error: str | None = None

    def sections(self) -> dict[str, str]:
        causes: list[str] = []
        for key, value in list(self.failures.items())[:5]:
            company = re.fullmatch(r"company_(\d{1,12})", key)
            label = (
                f"Garagem da empresa {company[1]}"
                if company
                else {"road": "Posições em operação", "companies": "Descoberta de empresas"}.get(
                    key, "Consulta"
                )
            )
            http = re.search(r":?http_(\d{3})\b", value)
            reason = (
                f"HTTP {http[1]}"
                if http
                else {
                    "session_expired": "sessão expirada",
                    "authentication_failed": "falha de autenticação",
                    "authentication_rejected": "credencial recusada",
                    "invalid_positions": "resposta de posições inválida",
                    "invalid_companies": "resposta de empresas inválida",
                    "cycle_deadline": "tempo limite do ciclo",
                }.get(value, "consulta indisponível")
            )
            causes.append(f"• {label}: {reason}.")
        if len(self.failures) > 5:
            causes.append(f"• Outras consultas com falha: {len(self.failures) - 5}.")
        if self.status == "storage_failure":
            causes.insert(0, "Falha de persistência no banco.")
            action = "Verificar conexão, permissões e espaço disponível no banco."
        elif self.error == "cycle_deadline":
            causes.insert(0, "O tempo limite do ciclo foi atingido.")
            action = "Verificar a disponibilidade da origem e a comunicação."
        elif any("authentication" in v or "session_expired" in v for v in self.failures.values()):
            action = "Verificar token e permissões da API. A reautenticação já é automática."
        elif any(re.search(r"http_5\d\d", v) for v in self.failures.values()):
            action = (
                "Aguardar a recuperação da origem e acompanhar. Reiniciar o coletor "
                "não corrige um erro de servidor da SPTrans."
            )
        else:
            action = "Conferir os logs e a disponibilidade da origem."
        impact = (
            "Operação: resposta gravada neste ciclo."
            if self.road_saved
            else "Operação: nenhuma resposta gravada neste ciclo."
        )
        if self.road_saved is None:
            impact = "Operação: confirmação de gravação indisponível."
        impact += (
            "\nGaragens: confirmação de gravação indisponível."
            if self.garages_saved is None
            else f"\nGaragens: {self.garages_saved} respostas gravadas."
        )
        if self.companies_discovered is False:
            impact += "\nDescoberta incompleta; cobertura total de garagens desconhecida."
        elif self.companies_discovered is None:
            impact += "\nDescoberta de empresas: sem confirmação."
        return {
            "Causa identificada": "\n".join(causes) or "Causa específica não disponível.",
            "Coleta preservada · último ciclo": impact,
            "Tentativas automáticas": (
                "Contagem indisponível neste incidente."
                if self.rounds is None
                else (
                    f"{self.rounds} rodadas de consulta; "
                    f"{max(0, self.rounds - 1)} rodadas de retentativa.\n"
                    "Consultas já gravadas não são repetidas no mesmo ciclo."
                )
            ),
            "Ação sugerida": action,
        }
