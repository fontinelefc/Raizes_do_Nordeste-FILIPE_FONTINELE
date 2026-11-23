"""E13 — Expiração de pedidos sem pagamento em 15 min (RN10; T4; UC14; D71).

A tarefa periódica fica desligada nos testes (``expiracao_intervalo=0`` no
conftest). Os testes chamam ``PedidoService.expirar_vencidos`` direto, com o
relógio fixo, na sessão da transação que é desfeita no fim (D64).
"""

from dataclasses import replace
from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import criar_app
from app.services.pedidos import PedidoService
from tests.apoio import (
    DEPOIS_DO_PRAZO,
    MEIO_DIA_RECIFE,
    PEDIDO_BALCAO,
    auth,
    consultar,
    criar_pedido,
    estoque,
)


def _expirar(sessao, config, momento) -> int:
    return PedidoService(sessao, config.jwt_segredo, lambda: momento).expirar_vencidos()


def test_expira_so_o_pedido_vencido_e_libera_a_reserva(api, config, sessao):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE
    antigo = criar_pedido(api)
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE + timedelta(minutes=10)
    recente = criar_pedido(api)
    assert estoque(sessao, 1, 1) == (50, 4)

    assert _expirar(sessao, config, DEPOIS_DO_PRAZO) == 1
    detalhe = consultar(api, antigo["id"], antigo["token_pedido"])
    assert detalhe["status"] == "EXPIRADO" and detalhe["expira_em"] is None
    assert detalhe["historico"][-1] == {"status": "EXPIRADO", "origem": "SISTEMA", "em": "2026-11-23T15:16:00Z"}
    assert consultar(api, recente["id"], recente["token_pedido"])["status"] == "AGUARDANDO_PAGAMENTO"
    assert estoque(sessao, 1, 1) == (50, 2)  # só a reserva do vencido voltou

    assert _expirar(sessao, config, DEPOIS_DO_PRAZO) == 0  # rodar de novo não muda nada


def test_pedido_pago_nao_expira(api, config, sessao, tokens):
    api.app.state.relogio = lambda: MEIO_DIA_RECIFE
    pedido = criar_pedido(api, PEDIDO_BALCAO, tokens["atendente_recife"])
    api.post(
        f"/api/v1/pedidos/{pedido['id']}/pagamentos/balcao",
        json={"forma": "DINHEIRO"},
        headers=auth(tokens["atendente_recife"]),
    )
    assert _expirar(sessao, config, DEPOIS_DO_PRAZO) == 0
    assert consultar(api, pedido["id"], tokens["atendente_recife"])["status"] == "PAGO"


def test_tarefa_periodica_sobe_e_para_com_a_aplicacao(config):
    """D71: com intervalo maior que zero, a tarefa nasce no lifespan e é cancelada no desligamento."""
    app = criar_app(replace(config, expiracao_intervalo=3600))
    with TestClient(app) as cliente:
        assert cliente.get("/api/v1/health").status_code == 200
