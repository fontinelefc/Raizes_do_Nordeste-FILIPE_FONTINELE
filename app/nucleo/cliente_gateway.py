"""Cliente do gateway de pagamento usado pelo PagamentoService (D33, D39, D72).

É a única porta da API para o gateway. Nesta entrega, ele chama o gateway
simulado dentro do mesmo processo, sem HTTP (D72). Para um gateway real, só esta
classe muda: as duas operações passam a ser chamadas HTTP com a chave de API, e
os eventos chegam pelo webhook, em vez de voltarem aqui.

Qualquer falha ao falar com o gateway vira 503 ``GATEWAY_INDISPONIVEL``. Sem o
gateway simulado (``GATEWAY_SIMULADO=false``), não há gateway configurado, e
toda chamada responde 503.
"""

import logging
from typing import TYPE_CHECKING

from app.nucleo.erros import ErroDominio

if TYPE_CHECKING:
    from app.services.gateway_simulado import EventoAssinado, GatewaySimuladoService

log = logging.getLogger("raizes")


def _indisponivel() -> ErroDominio:
    return ErroDominio("GATEWAY_INDISPONIVEL", "Gateway de pagamento indisponível; tente de novo")


class ClienteGateway:
    def __init__(self, gateway: "GatewaySimuladoService | None") -> None:
        self._gateway = gateway

    def criar_cobranca(self, referencia: str, valor: str, forma: str) -> str:
        """Devolve o ``transacao_id``; a mesma referência devolve a mesma transação (D39)."""
        if self._gateway is None:
            raise _indisponivel()
        try:
            cobranca, _ = self._gateway.criar_cobranca(referencia, valor, forma)
        except Exception:
            log.exception("falha ao criar cobrança no gateway, referencia=%s", referencia)
            raise _indisponivel() from None
        return cobranca.transacao_id

    def solicitar_estorno(self, transacao_id: str) -> "EventoAssinado":
        """Pede o estorno (UC13). No simulado, o ``refund.completed`` volta aqui para ser entregue ao webhook."""
        if self._gateway is None:
            raise _indisponivel()
        return self._gateway.estornar(transacao_id)
