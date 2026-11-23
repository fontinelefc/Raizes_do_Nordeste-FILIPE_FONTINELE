"""Tipos e modelos compartilhados pelas views (convenções da seção 3.6.1, D40, D41)."""

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# Dinheiro como texto decimal com 2 casas (ex.: "18.90"), nunca float
Dinheiro = Annotated[str, Field(pattern=r"^\d{1,8}\.\d{2}$", examples=["18.90"])]

# Validação simples de e-mail sem dependência extra (D18); o formato fica no contrato
Email = Annotated[str, Field(max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]

def _em_utc(valor: datetime) -> datetime:
    # O MySQL devolve DATETIME sem fuso; o banco grava em UTC (M12, D55)
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor.astimezone(timezone.utc)


# ISO 8601 em UTC, ex.: "2026-11-22T19:45:00Z" (3.6.1)
DataHora = Annotated[datetime, AfterValidator(_em_utc)]


class Entrada(BaseModel):
    """Base dos corpos de requisição: campos extras são recusados (D40)."""

    model_config = ConfigDict(extra="forbid")


class Saida(BaseModel):
    """Base dos corpos de resposta."""


class Saude(Saida):
    """Resposta do health check (D38)."""

    status: str = Field(examples=["ok"])
    banco: str = Field(examples=["ok"])


# ---- Formato único de erro (D41) ----

class DetalheErro(Saida):
    campo: str | None = None
    valor: Any = None
    problema: str | None = None


class CorpoErro(Saida):
    codigo: str = Field(examples=["ESTOQUE_INSUFICIENTE"])
    mensagem: str
    detalhes: list[DetalheErro] | None = None
    request_id: str


class Erro(Saida):
    erro: CorpoErro


_DESCRICAO_ERRO = {
    401: "NAO_AUTENTICADO, CREDENCIAIS_INVALIDAS ou ASSINATURA_INVALIDA",
    403: "SEM_PERMISSAO",
    404: "NAO_ENCONTRADO (inclui recurso de outro cliente) ou TRANSACAO_DESCONHECIDA",
    409: "Conflito com o estado atual (ver tabela da seção 3.6.4)",
    422: "VALIDACAO ou regra de valor (PRECO_FORA_DA_FAIXA, JUSTIFICATIVA_OBRIGATORIA, "
    "AUTORIZACAO_RESPONSAVEL_OBRIGATORIA)",
    503: "GATEWAY_INDISPONIVEL ou BANCO_INDISPONIVEL",
}


def respostas_erro(*status: int) -> dict[int | str, dict[str, Any]]:
    """Monta o ``responses`` de uma rota com o formato único de erro."""
    return {s: {"model": Erro, "description": _DESCRICAO_ERRO[s]} for s in status}
