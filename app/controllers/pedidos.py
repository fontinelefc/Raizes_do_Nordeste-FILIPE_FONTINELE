"""Rotas do domínio Pedidos (endpoints 12–16). Service: PedidoService (E12).

O controller só valida o formato (view) e chama o service (D32, D50). Como as
regras de quem pode o quê dependem do pedido (canal, unidade, dono), a
autorização fica no service; aqui só se exige um token válido, ou nenhum, na
criação de pedido anônimo (D12, D46).
"""

import logging

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request, Response, status

from app.controllers.pagamentos import pedir_estornos
from app.controllers.parametros import IP, TOKEN, TOKEN_OPCIONAL, Id, Limit, Offset, Sessao
from app.models.enums import StatusPedido
from app.nucleo.banco import abrir_sessao
from app.services.pedidos import PedidoService
from app.views.comum import respostas_erro
from app.views.pedidos import (
    CancelamentoEntrada,
    ListaPedidos,
    Pedido,
    PedidoDetalhe,
    PedidoEntrada,
    StatusPedidoEntrada,
)

log = logging.getLogger("raizes")

router = APIRouter(tags=["Pedidos"])


def _service(request: Request, sessao: Sessao) -> PedidoService:
    return PedidoService(sessao, request.app.state.config.jwt_segredo, request.app.state.relogio)


@router.post(
    "/pedidos",
    summary="Criar pedido multicanal (RF09, RF15, UC02, UC03)",
    description=(
        "CLIENTE (APP, PICKUP); ATENDENTE da unidade (BALCAO); sem login "
        "(APP, TOTEM, PICKUP), com devolução de token_pedido (D46). "
        "O preço vem sempre de item_cardapio."
    ),
    status_code=status.HTTP_201_CREATED,
    response_model=Pedido,
    responses=respostas_erro(401, 403, 404, 409, 422),
)
def criar_pedido(
    dados: PedidoEntrada, ator: TOKEN_OPCIONAL, request: Request, response: Response, sessao: Sessao
) -> Pedido:
    pedido = _service(request, sessao).criar(ator, dados)
    response.headers["Location"] = f"{request.url.path}/{pedido.id}"
    return pedido


@router.get(
    "/pedidos/{id}",
    summary="Consultar pedido e histórico de status (RF10, UC10)",
    response_model=PedidoDetalhe,
    responses=respostas_erro(401, 404),
)
def consultar_pedido(id: Id, ator: TOKEN, request: Request, sessao: Sessao) -> PedidoDetalhe:
    return _service(request, sessao).consultar(ator, id)


@router.get(
    "/unidades/{id}/pedidos",
    summary="Painel de pedidos da unidade — funcionário da unidade, MATRIZ (RF10, RF11, UC11)",
    response_model=ListaPedidos,
    responses=respostas_erro(401, 403, 404),
)
def painel_pedidos(
    id: Id,
    ator: TOKEN,
    request: Request,
    sessao: Sessao,
    status: StatusPedido | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ListaPedidos:
    return _service(request, sessao).painel(ator, id, status, limit, offset)


@router.patch(
    "/pedidos/{id}/status",
    summary="Avançar status — COZINHA (EM_PREPARO, PRONTO), ATENDENTE (ENTREGUE) (RF11, UC11)",
    response_model=Pedido,
    responses=respostas_erro(401, 403, 404, 409, 422),
)
def avancar_status(id: Id, dados: StatusPedidoEntrada, ator: TOKEN, request: Request, sessao: Sessao) -> Pedido:
    return _service(request, sessao).avancar(ator, id, dados)


@router.post(
    "/pedidos/{id}/cancelamento",
    summary="Cancelar pedido com justificativa — dono (T5, T9), GERENTE da unidade (T5, T9–T11) (RF12, UC12)",
    response_model=Pedido,
    responses=respostas_erro(401, 403, 404, 409, 422),
)
def cancelar_pedido(
    id: Id,
    dados: CancelamentoEntrada,
    ator: TOKEN,
    ip: IP,
    request: Request,
    sessao: Sessao,
    tarefas: BackgroundTasks,
) -> Pedido:
    servico = _service(request, sessao)
    pedido = servico.cancelar(ator, id, dados, ip)
    if servico.estornos:  # T9–T11 pago online: estorno ao gateway depois do COMMIT (D33, D69)
        tarefas.add_task(pedir_estornos, request.app, sessao, list(servico.estornos))
    return pedido


# ---- Tarefa periódica (T4; RN10; UC14; D71) ----

def expirar_pedidos(app: FastAPI) -> int:
    """Uma rodada da expiração; chamada pelo lifespan do ``main.py`` a cada EXPIRACAO_INTERVALO segundos.

    Faz o papel de controller da tarefa: abre a própria sessão, porque não há
    requisição, e chama o service, que faz o COMMIT.
    """
    sessao = abrir_sessao(app.state.config)
    try:
        expirados = PedidoService(sessao, app.state.config.jwt_segredo, app.state.relogio).expirar_vencidos()
    finally:
        sessao.close()
    if expirados:
        log.info("expiração: %d pedido(s) expirado(s)", expirados)
    return expirados
