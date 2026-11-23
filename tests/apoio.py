"""Dados da carga de exemplo e auxiliares usados pelos testes de integração (D64)."""

SENHA_EXEMPLO = "Raizes@2026"  # senha de todas as contas da carga (D55)

FUNCIONARIOS = {
    "matriz": "matriz@raizes.example",
    "gerente_recife": "gerente.recife@raizes.example",
    "atendente_recife": "atendente.recife@raizes.example",
    "cozinha_recife": "cozinha.recife@raizes.example",
    "gerente_fortaleza": "gerente.fortaleza@raizes.example",
    "atendente_fortaleza": "atendente.fortaleza@raizes.example",
    "cozinha_fortaleza": "cozinha.fortaleza@raizes.example",
}
CLIENTES = {"maria": "maria@cliente.example", "joao": "joao@cliente.example"}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def codigo(resposta) -> str:
    """Os testes verificam ``erro.codigo``, não o texto da mensagem (D41)."""
    return resposta.json()["erro"]["codigo"]


# ---- Apoio da E13 (pagamentos, webhook e expiração) ----

from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import text  # noqa: E402

MEIO_DIA_RECIFE = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)  # 12:00 em UTC−3 (D70)
DEPOIS_DO_PRAZO = MEIO_DIA_RECIFE + timedelta(minutes=16)  # RN10: 15 min para pagar
PEDIDO_APP = {"unidade_id": 1, "canal": "APP", "itens": [{"produto_id": 1, "quantidade": 2}, {"produto_id": 5, "quantidade": 1}]}
PEDIDO_BALCAO = {"unidade_id": 1, "canal": "BALCAO", "itens": [{"produto_id": 1, "quantidade": 2}]}


def estoque(sessao, unidade_id: int, produto_id: int) -> tuple[int, int]:
    """(quantidade, quantidade_reservada) de um produto na unidade."""
    linha = sessao.execute(
        text("SELECT quantidade, quantidade_reservada FROM estoque WHERE unidade_id = :u AND produto_id = :p"),
        {"u": unidade_id, "p": produto_id},
    ).one()
    return linha.quantidade, linha.quantidade_reservada


def chave_gateway(config) -> dict[str, str]:
    return {"X-Api-Key": config.gateway_chave_api}


def criar_pedido(api, corpo=PEDIDO_APP, token: str | None = None) -> dict:
    resposta = api.post("/api/v1/pedidos", json=corpo, headers=auth(token) if token else {})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def pagar_online(api, pedido_id: int, token: str, forma: str = "PIX"):
    return api.post(f"/api/v1/pedidos/{pedido_id}/pagamentos", json={"forma": forma}, headers=auth(token))


def decidir(api, config, transacao_id: str, resultado: str, motivo: str | None = None):
    return api.post(
        f"/api/v1/gateway-simulado/cobrancas/{transacao_id}/resultado",
        json={"resultado": resultado, "motivo": motivo},
        headers=chave_gateway(config),
    )


def consultar(api, pedido_id: int, token: str) -> dict:
    resposta = api.get(f"/api/v1/pedidos/{pedido_id}", headers=auth(token))
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


# ---- Apoio da E14 (fidelidade, LGPD e auditoria) ----

import json  # noqa: E402

CONSENTIMENTO = {"finalidade": "FIDELIDADE", "versao_termo": "1.0"}


def saldo(sessao, cliente_id: int) -> int:
    return sessao.scalar(text("SELECT saldo_pontos FROM cliente WHERE id = :id"), {"id": cliente_id})


def auditoria(sessao, acao: str) -> list[dict]:
    """Registros de uma ação, do mais antigo ao mais novo, com ``detalhes`` já decodificado."""
    linhas = sessao.execute(
        text(
            "SELECT ator_tipo, ator_id, acao, entidade, entidade_id, unidade_id, detalhes, ip_origem "
            "FROM registro_auditoria WHERE acao = :acao ORDER BY id"
        ),
        {"acao": acao},
    ).mappings()
    registros = []
    for linha in linhas:
        registro = dict(linha)
        if isinstance(registro["detalhes"], str):
            registro["detalhes"] = json.loads(registro["detalhes"])
        registros.append(registro)
    return registros


def pedido_pago_online(api, config, token: str, corpo=PEDIDO_APP) -> dict:
    """Pedido do cliente pago pelo gateway simulado (T2)."""
    pedido = criar_pedido(api, corpo, token)
    pagamento = pagar_online(api, pedido["id"], token)
    assert pagamento.status_code == 202, pagamento.text
    decidir(api, config, pagamento.json()["transacao_gateway"], "APROVADO")
    return pedido
