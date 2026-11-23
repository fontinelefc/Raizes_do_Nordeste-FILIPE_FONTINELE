"""Tabela ``historico_status_pedido`` (RF10–RF12; RN07; M04: uma linha por transição). Service dono: PedidoService."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_mysql
from app.models.enums import OrigemAcao, StatusPedido


class HistoricoStatusPedido(Base):
    __tablename__ = "historico_status_pedido"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pedido_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pedido.id"))
    status_anterior: Mapped[StatusPedido | None] = mapped_column(enum_mysql(StatusPedido))  # NULL na criação
    status_novo: Mapped[StatusPedido] = mapped_column(enum_mysql(StatusPedido))
    origem: Mapped[OrigemAcao] = mapped_column(enum_mysql(OrigemAcao))
    motivo: Mapped[str | None] = mapped_column(String(255))
    criado_em: Mapped[datetime] = mapped_column(DateTime)
