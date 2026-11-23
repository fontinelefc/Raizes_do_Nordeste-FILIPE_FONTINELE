"""Views do domínio Pedidos (RF09–RF12)."""

from typing import Literal

from pydantic import Field

from app.models.enums import Canal, OrigemAcao, StatusPedido
from app.views.comum import DataHora, Dinheiro, Entrada, Saida
from app.views.pagamentos import Pagamento


class ItemPedidoEntrada(Entrada):
    produto_id: int = Field(ge=1)
    quantidade: int = Field(ge=1, le=20)


class PedidoEntrada(Entrada):
    # Sem campo de preço: o preço vem sempre de item_cardapio
    unidade_id: int = Field(ge=1)
    canal: Canal
    itens: list[ItemPedidoEntrada] = Field(min_length=1, max_length=20)


class ItemPedido(Saida):
    produto_id: int
    nome: str
    quantidade: int
    preco_unitario: Dinheiro
    subtotal: Dinheiro


class Pedido(Saida):
    id: int
    unidade_id: int
    cliente_id: int | None = None
    canal: Canal
    status: StatusPedido
    valor_total: Dinheiro
    expira_em: DataHora | None = None
    criado_em: DataHora
    itens: list[ItemPedido]
    token_pedido: str | None = Field(default=None, description="Só em pedido anônimo (D46)")


class HistoricoStatus(Saida):
    status: StatusPedido
    origem: OrigemAcao
    em: DataHora


class PedidoDetalhe(Pedido):
    historico: list[HistoricoStatus]
    pagamento: Pagamento | None = None


class ListaPedidos(Saida):
    itens: list[Pedido]
    total: int


class StatusPedidoEntrada(Entrada):
    # Transições manuais T6–T8; as demais são do sistema ou do gateway (D31)
    status: Literal["EM_PREPARO", "PRONTO", "ENTREGUE"]


class CancelamentoEntrada(Entrada):
    justificativa: str = Field(min_length=10, max_length=255)
