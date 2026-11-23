"""Tabela ``produto`` (catálogo padrão da matriz; RF04; RN01, RN02). Service dono: UnidadeService."""

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, FetchedValue, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Produto(Base):
    __tablename__ = "produto"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    nome: Mapped[str] = mapped_column(String(100))
    descricao: Mapped[str | None] = mapped_column(String(255))
    categoria: Mapped[str] = mapped_column(String(50))
    preco_base: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    preco_minimo: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    preco_maximo: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    exige_cozinha_completa: Mapped[bool] = mapped_column(Boolean, server_default=FetchedValue())
    ativo: Mapped[bool] = mapped_column(Boolean, server_default=FetchedValue())
