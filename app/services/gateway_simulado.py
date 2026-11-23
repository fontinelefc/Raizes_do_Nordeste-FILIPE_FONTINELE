"""GatewaySimuladoService: faz o papel do gateway de pagamento externo (D39, D44, D72, D73).

Só existe com ``GATEWAY_SIMULADO=true``. Não tem tabela: as cobranças ficam em
memória (``MemoriaGateway`` em ``app.state``, D73) e somem quando a API
reinicia, como aconteceria com um sistema de outra empresa que a API não
controla. Um lock protege o dicionário, porque o Uvicorn atende rotas
síncronas em várias threads.

O que o gateway faz, e o que um gateway real faria por HTTP:

* ``criar_cobranca``: a mesma referência (``pedido_id``) devolve a mesma
  transação (D39). É isso que permite à API tentar de novo depois de um 503
  sem cobrar duas vezes (ERR-003).
* ``decidir``: aprova ou recusa a cobrança (rota de teste) e devolve o evento
  ``payment.approved`` ou ``payment.refused`` já assinado com HMAC (D43).
* ``estornar``: estorna uma cobrança aprovada e devolve o evento
  ``refund.completed``.

Os eventos devolvidos são entregues ao webhook da API depois da resposta, em
segundo plano (ver ``controllers/pagamentos.entregar_webhook``).
"""

import json
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.nucleo.erros import ErroDominio
from app.nucleo.seguranca import assinar

TIPO_EVENTO = {"APROVADO": "payment.approved", "RECUSADO": "payment.refused", "ESTORNADO": "refund.completed"}


@dataclass
class CobrancaSimulada:
    transacao_id: str
    referencia: str
    valor: str
    forma: str
    status: str = "PENDENTE"  # PENDENTE → APROVADO | RECUSADO; APROVADO → ESTORNADO


@dataclass
class MemoriaGateway:
    """Estado do gateway simulado (D73): uma instância por aplicação."""

    por_transacao: dict[str, CobrancaSimulada] = field(default_factory=dict)
    por_referencia: dict[str, str] = field(default_factory=dict)
    trava: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class EventoAssinado:
    """Corpo do webhook e o cabeçalho X-Assinatura, como o gateway mandaria por HTTP."""

    corpo: bytes
    assinatura: str


def _nao_encontrada() -> ErroDominio:
    return ErroDominio("TRANSACAO_DESCONHECIDA", "Transação não encontrada no gateway")


def _conflito(cobranca: CobrancaSimulada, pedido: str) -> ErroDominio:
    return ErroDominio(
        "TRANSICAO_INVALIDA",
        "A cobrança não está no estado esperado",
        [{"campo": "transacao_id", "valor": cobranca.transacao_id, "problema": f"status atual: {cobranca.status}; pedido: {pedido}"}],
    )


class GatewaySimuladoService:
    def __init__(self, memoria: MemoriaGateway, webhook_segredo: str, relogio: Callable[[], datetime]) -> None:
        self.memoria = memoria
        self.webhook_segredo = webhook_segredo
        self.relogio = relogio

    def criar_cobranca(self, referencia: str, valor: str, forma: str) -> tuple[CobrancaSimulada, bool]:
        """Devolve (cobrança, criada). ``criada`` é False quando a referência já existia (D39)."""
        with self.memoria.trava:
            existente = self.memoria.por_referencia.get(referencia)
            if existente is not None:
                return self.memoria.por_transacao[existente], False
            cobranca = CobrancaSimulada("sim_" + secrets.token_hex(6), referencia, valor, forma)
            self.memoria.por_transacao[cobranca.transacao_id] = cobranca
            self.memoria.por_referencia[referencia] = cobranca.transacao_id
            return cobranca, True

    def decidir(self, transacao_id: str, resultado: str, motivo: str | None) -> EventoAssinado:
        """PENDENTE → APROVADO ou RECUSADO; uma cobrança já decidida responde 409."""
        with self.memoria.trava:
            cobranca = self._obter(transacao_id)
            if cobranca.status != "PENDENTE":
                raise _conflito(cobranca, resultado)
            cobranca.status = resultado
        return self._evento(cobranca, motivo if resultado == "RECUSADO" else None)

    def estornar(self, transacao_id: str) -> EventoAssinado:
        """APROVADO → ESTORNADO (UC13); só uma cobrança aprovada pode ser estornada."""
        with self.memoria.trava:
            cobranca = self._obter(transacao_id)
            if cobranca.status != "APROVADO":
                raise _conflito(cobranca, "ESTORNADO")
            cobranca.status = "ESTORNADO"
        return self._evento(cobranca, None)

    def _obter(self, transacao_id: str) -> CobrancaSimulada:
        cobranca = self.memoria.por_transacao.get(transacao_id)
        if cobranca is None:
            raise _nao_encontrada()
        return cobranca

    def _evento(self, cobranca: CobrancaSimulada, motivo: str | None) -> EventoAssinado:
        dados = {
            "evento_id": "evt_" + secrets.token_hex(8),
            "tipo": TIPO_EVENTO[cobranca.status],
            "transacao_id": cobranca.transacao_id,
            "referencia": cobranca.referencia,
            "status": cobranca.status,
            "motivo": motivo,
            "ocorrido_em": self.relogio().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        return EventoAssinado(corpo, assinar(corpo, self.webhook_segredo))
