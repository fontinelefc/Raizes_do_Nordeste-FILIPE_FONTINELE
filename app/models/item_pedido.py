"""Tabela ``item_pedido`` (RF09; M08: preço copiado do cardápio no momento do pedido). Service dono: PedidoService."""

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.produto import Produto


class ItemPedido(Base):
    __tablename__ = "item_pedido"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pedido_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pedido.id"))
    produto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("produto.id"))
    quantidade: Mapped[int] = mapped_column(Integer)
    preco_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    produto: Mapped[Produto] = relationship(lazy="joined")
