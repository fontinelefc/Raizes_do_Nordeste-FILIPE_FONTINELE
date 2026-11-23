"""Tabela ``pedido`` (RF09–RF12; RN06, RN07, RN10; D07, D31). Service dono: PedidoService."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, FetchedValue, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_mysql
from app.models.enums import Canal, StatusPedido
from app.models.historico_status_pedido import HistoricoStatusPedido
from app.models.item_pedido import ItemPedido


class Pedido(Base):
    __tablename__ = "pedido"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    unidade_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("unidade.id"))
    cliente_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cliente.id"))  # NULL = anônimo (M07)
    canal: Mapped[Canal] = mapped_column(enum_mysql(Canal))
    status: Mapped[StatusPedido] = mapped_column(enum_mysql(StatusPedido))
    valor_total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expira_em: Mapped[datetime | None] = mapped_column(DateTime)
    criado_em: Mapped[datetime] = mapped_column(DateTime)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())

    itens: Mapped[list[ItemPedido]] = relationship(lazy="selectin", order_by=ItemPedido.id)
    historico: Mapped[list[HistoricoStatusPedido]] = relationship(
        lazy="selectin", order_by=HistoricoStatusPedido.id
    )
