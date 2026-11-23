"""Views do domínio Fidelidade e LGPD (RF17, RF20, RF25)."""

from pydantic import Field

from app.models.enums import Finalidade, TipoMovPontos
from app.views.comum import DataHora, Entrada, Saida


class MovimentacaoPontos(Saida):
    id: int
    pedido_id: int | None = None
    tipo: TipoMovPontos
    pontos: int
    criado_em: DataHora


class ListaMovimentacoes(Saida):
    itens: list[MovimentacaoPontos]
    total: int


class ConsentimentoEntrada(Entrada):
    finalidade: Finalidade
    versao_termo: str = Field(max_length=10)
    autorizado_responsavel: bool = False  # obrigatório para MENOR_18 (regra no service)


class Consentimento(Saida):
    id: int
    finalidade: Finalidade
    versao_termo: str
    autorizado_responsavel: bool
    concedido_em: DataHora
    revogado_em: DataHora | None = None
