"""Tabela ``movimentacao_pontos`` (RF17; RN14; M11: extrato, com o saldo em ``cliente.saldo_pontos``). Service dono: FidelidadeService."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, FetchedValue, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_mysql
from app.models.enums import TipoMovPontos


class MovimentacaoPontos(Base):
    __tablename__ = "movimentacao_pontos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cliente.id"))
    pedido_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pedido.id"))
    tipo: Mapped[TipoMovPontos] = mapped_column(enum_mysql(TipoMovPontos))
    pontos: Mapped[int] = mapped_column(Integer)  # positivo no crédito, negativo no estorno (CHECK no banco)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
