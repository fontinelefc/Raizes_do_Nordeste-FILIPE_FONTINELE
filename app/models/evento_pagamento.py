"""Tabela ``evento_pagamento`` (RF14; D09, D43; M06/D28: idempotência do webhook). Service dono: PagamentoService.

A chave única ``evento_gateway`` é o que torna o webhook idempotente: o mesmo
evento recebido duas vezes esbarra nela e responde 200 ``REPETIDO``.
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, FetchedValue, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EventoPagamento(Base):
    __tablename__ = "evento_pagamento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    evento_gateway: Mapped[str] = mapped_column(String(100))  # UNIQUE no banco
    pagamento_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pagamento.id"))
    tipo: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)  # sem dados de cartão (RN09)
    recebido_em: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
    processado_em: Mapped[datetime | None] = mapped_column(DateTime)
