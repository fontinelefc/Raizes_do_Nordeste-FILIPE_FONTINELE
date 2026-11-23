"""Tabela ``pagamento`` (RF13, RF14; RN09; D14, D24; M05/D28: um pagamento por pedido). Service dono: PagamentoService."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, FetchedValue, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_mysql
from app.models.enums import FormaPagamento, StatusPagamento, TipoPagamento


class Pagamento(Base):
    __tablename__ = "pagamento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pedido_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pedido.id"))  # UNIQUE no banco (M05)
    tipo: Mapped[TipoPagamento] = mapped_column(enum_mysql(TipoPagamento))
    forma: Mapped[FormaPagamento] = mapped_column(enum_mysql(FormaPagamento))
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[StatusPagamento] = mapped_column(enum_mysql(StatusPagamento))
    # NULL no balcão e até o gateway responder (D39); UNIQUE no banco
    transacao_gateway: Mapped[str | None] = mapped_column(String(100))
    motivo_recusa: Mapped[str | None] = mapped_column(String(255))
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
