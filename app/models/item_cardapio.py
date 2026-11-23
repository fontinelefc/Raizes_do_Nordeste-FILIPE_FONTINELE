"""Tabela ``item_cardapio`` (associativa unidade × produto, M02; RF05, RF08). Service dono: UnidadeService."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, FetchedValue, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.produto import Produto


class ItemCardapio(Base):
    __tablename__ = "item_cardapio"

    unidade_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("unidade.id"), primary_key=True)
    produto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("produto.id"), primary_key=True)
    preco: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    disponivel: Mapped[bool] = mapped_column(Boolean, server_default=FetchedValue())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())

    produto: Mapped[Produto] = relationship(lazy="joined")
