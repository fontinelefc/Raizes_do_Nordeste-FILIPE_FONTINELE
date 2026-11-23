"""Views do domínio Unidades e catálogo (RF03–RF05, RF08)."""

from pydantic import Field

from app.models.enums import TipoOperacao
from app.views.comum import DataHora, Dinheiro, Entrada, Saida

# ---- Unidades ----

class UnidadeEntrada(Entrada):
    nome: str = Field(max_length=100)
    tipo_operacao: TipoOperacao
    cidade: str = Field(max_length=80)
    uf: str = Field(pattern=r"^[A-Z]{2}$")
    horario_abertura: str = Field(examples=["06:00"])
    horario_fechamento: str = Field(examples=["22:00"])


class UnidadeAlteracao(Entrada):
    nome: str | None = Field(default=None, max_length=100)
    tipo_operacao: TipoOperacao | None = None
    horario_abertura: str | None = None
    horario_fechamento: str | None = None
    ativa: bool | None = None


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
    nome: str | None = Field(default=None, max_length=100)
    descricao: str | None = Field(default=None, max_length=255)
    categoria: str | None = Field(default=None, max_length=50)
    preco_base: Dinheiro | None = None
    preco_minimo: Dinheiro | None = None
    preco_maximo: Dinheiro | None = None
    exige_cozinha_completa: bool | None = None
    ativo: bool | None = None


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
