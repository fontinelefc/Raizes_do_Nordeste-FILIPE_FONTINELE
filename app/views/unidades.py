"""Views do domínio Unidades e catálogo (RF03–RF05, RF08)."""

from typing import Annotated

from pydantic import Field

from app.models.enums import TipoOperacao
from app.views.comum import DataHora, Dinheiro, Entrada, Saida, SemNulo

# ---- Unidades ----

class UnidadeEntrada(Entrada):
    nome: str = Field(max_length=100)
    tipo_operacao: TipoOperacao
    cidade: str = Field(max_length=80)
    uf: str = Field(pattern=r"^[A-Z]{2}$")
    horario_abertura: str = Field(examples=["06:00"])
    horario_fechamento: str = Field(examples=["22:00"])


class UnidadeAlteracao(Entrada):
    # Campos opcionais que não aceitam null (o service recusa; E17)
    nome: Annotated[str, Field(max_length=100)] | SemNulo = None
    tipo_operacao: TipoOperacao | SemNulo = None
    horario_abertura: str | SemNulo = None
    horario_fechamento: str | SemNulo = None
    ativa: bool | SemNulo = None


class Unidade(UnidadeEntrada):
    id: int
    ativa: bool
    criado_em: DataHora


class ListaUnidades(Saida):
    itens: list[Unidade]
    total: int


# ---- Catálogo padrão da matriz (D05) ----

class ProdutoEntrada(Entrada):
    codigo: str = Field(max_length=20)
    nome: str = Field(max_length=100)
    descricao: str | None = Field(default=None, max_length=255)
    categoria: str = Field(max_length=50)
    preco_base: Dinheiro
    preco_minimo: Dinheiro
    preco_maximo: Dinheiro
    exige_cozinha_completa: bool


class ProdutoAlteracao(Entrada):
    # Só a descrição aceita null (apaga o texto); os demais o service recusa (E17)
    nome: Annotated[str, Field(max_length=100)] | SemNulo = None
    descricao: str | None = Field(default=None, max_length=255)
    categoria: Annotated[str, Field(max_length=50)] | SemNulo = None
    preco_base: Dinheiro | SemNulo = None
    preco_minimo: Dinheiro | SemNulo = None
    preco_maximo: Dinheiro | SemNulo = None
    exige_cozinha_completa: bool | SemNulo = None
    ativo: bool | SemNulo = None


class Produto(ProdutoEntrada):
    id: int
    ativo: bool


class ListaProdutos(Saida):
    itens: list[Produto]
    total: int


# ---- Cardápio da unidade (preço e disponibilidade locais) ----

class ItemCardapioEntrada(Entrada):
    preco: Dinheiro
    disponivel: bool


class ItemCardapio(Saida):
    produto_id: int
    nome: str
    descricao: str | None = None
    categoria: str
    preco: Dinheiro
    disponivel: bool


class ListaItensCardapio(Saida):
    itens: list[ItemCardapio]
    total: int
