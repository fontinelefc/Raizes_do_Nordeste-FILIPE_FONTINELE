"""Views do domínio Estoque (RF15)."""

from pydantic import Field

from app.views.comum import DataHora, Saida


class Estoque(Saida):
    produto_id: int
    quantidade: int
    quantidade_reservada: int
    disponivel: int = Field(description="quantidade - quantidade_reservada")
    atualizado_em: DataHora


class ListaEstoque(Saida):
    itens: list[Estoque]
    total: int
