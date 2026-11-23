"""Views do gateway simulado (D39, D44): só usadas com GATEWAY_SIMULADO=true."""

from typing import Literal

from pydantic import Field

from app.views.comum import Dinheiro, Entrada, Saida


class CobrancaEntrada(Entrada):
    referencia: str = Field(description="pedido_id; chave de idempotência (D39)")
    valor: Dinheiro
    forma: Literal["PIX", "CARTAO_CREDITO", "CARTAO_DEBITO"]


class Cobranca(Saida):
    transacao_id: str = Field(examples=["sim_8f3a2c"])
    referencia: str
    status: Literal["PENDENTE", "APROVADO", "RECUSADO", "ESTORNADO"]


class ResultadoCobrancaEntrada(Entrada):
    resultado: Literal["APROVADO", "RECUSADO"]
    motivo: str | None = Field(default=None, max_length=255)


class EstornoEntrada(Entrada):
    transacao_id: str
