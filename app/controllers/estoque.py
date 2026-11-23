"""Rotas do domínio Estoque (endpoint 11). Service: EstoqueService (E12).

A autorização por função vem da dependência MATRIZ_OU_GERENTE; a checagem da
unidade do GERENTE fica no service.
"""

from fastapi import APIRouter

from app.controllers.parametros import MATRIZ_OU_GERENTE, Id, Limit, Offset, Sessao
from app.services.estoque import EstoqueService
from app.views.comum import respostas_erro
from app.views.estoque import ListaEstoque

router = APIRouter(tags=["Estoque"])


@router.get(
    "/unidades/{id}/estoque",
    summary="Consultar estoque da unidade — GERENTE da unidade, MATRIZ (RF15)",
    response_model=ListaEstoque,
    responses=respostas_erro(401, 403, 404, 422),
)
def consultar_estoque(
    id: Id, ator: MATRIZ_OU_GERENTE, sessao: Sessao, limit: Limit = 20, offset: Offset = 0
) -> ListaEstoque:
    return EstoqueService(sessao).listar(ator, id, limit, offset)
