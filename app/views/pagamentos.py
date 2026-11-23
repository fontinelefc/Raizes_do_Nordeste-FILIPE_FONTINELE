"""Views do domínio Pagamentos (RF13, RF14, webhook D43)."""

from typing import Literal

from pydantic import Field

from app.models.enums import FormaPagamento, StatusPagamento, TipoPagamento
from app.views.comum import DataHora, Dinheiro, Entrada, Saida

FormaOnline = Literal["PIX", "CARTAO_CREDITO", "CARTAO_DEBITO"]


class PagamentoOnlineEntrada(Entrada):
    forma: FormaOnline


class PagamentoBalcaoEntrada(Entrada):
    forma: FormaPagamento  # inclui DINHEIRO (D14)


class Pagamento(Saida):
    pagamento_id: int
    pedido_id: int
    tipo: TipoPagamento
    forma: FormaPagamento
    valor: Dinheiro
    status: StatusPagamento
    transacao_gateway: str | None = None
    motivo_recusa: str | None = None


class EventoWebhook(Entrada):
    evento_id: str = Field(max_length=100)
    tipo: Literal["payment.approved", "payment.refused", "refund.completed"]
    transacao_id: str = Field(max_length=100)
    referencia: str = Field(description="pedido_id")
    status: Literal["APROVADO", "RECUSADO", "ESTORNADO"]
    motivo: str | None = Field(default=None, max_length=255)
    ocorrido_em: DataHora


class ResultadoWebhook(Saida):
    resultado: Literal["PROCESSADO", "REPETIDO"]
