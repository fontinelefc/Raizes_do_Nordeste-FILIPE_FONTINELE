"""Tabela ``estoque`` (saldo por unidade e produto; RF15; RN06, D27). Service dono: EstoqueService."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, FetchedValue, ForeignKeyConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Estoque(Base):
    __tablename__ = "estoque"
    # FK composta para item_cardapio: só há estoque de produto que está no cardápio da unidade
    __table_args__ = (
        ForeignKeyConstraint(
            ["unidade_id", "produto_id"], ["item_cardapio.unidade_id", "item_cardapio.produto_id"]
        ),
    )

    unidade_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    produto_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    quantidade: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())
    quantidade_reservada: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
