"""Rotas do domínio Unidades e catálogo (endpoints 3–10). Service: UnidadeService (E11).

O controller só valida o formato (view) e chama o service (D32, D50). A
autorização por função vem das dependências SO_MATRIZ e MATRIZ_OU_GERENTE;
a checagem da unidade do GERENTE fica no service.
"""

from fastapi import APIRouter, status

from app.controllers.parametros import IP, MATRIZ_OU_GERENTE, SO_MATRIZ, Id, Limit, Offset, ProdutoId, Sessao
from app.services.unidades import UnidadeService
from app.views.comum import respostas_erro
from app.views.unidades import (
    ItemCardapio,
    ItemCardapioEntrada,
    ListaItensCardapio,
    ListaProdutos,
    ListaUnidades,
    Produto,
    ProdutoAlteracao,
    ProdutoEntrada,
    Unidade,
    UnidadeAlteracao,
    UnidadeEntrada,
)

router = APIRouter(tags=["Unidades e catálogo"])


@router.get(
    "/unidades",
    summary="Listar unidades ativas (RF03, RF08, UC01)",
    response_model=ListaUnidades,
    responses=respostas_erro(422),
)
def listar_unidades(sessao: Sessao, limit: Limit = 20, offset: Offset = 0) -> ListaUnidades:
    return UnidadeService(sessao).listar_unidades(limit, offset)


@router.post(
    "/unidades",
    summary="Cadastrar unidade — MATRIZ (RF03, UC17)",
    status_code=status.HTTP_201_CREATED,
    response_model=Unidade,
    responses=respostas_erro(401, 403, 422),
)
def cadastrar_unidade(dados: UnidadeEntrada, ator: SO_MATRIZ, ip: IP, sessao: Sessao) -> Unidade:
    return UnidadeService(sessao).cadastrar_unidade(ator, dados, ip)


@router.patch(
    "/unidades/{id}",
    summary="Alterar unidade — MATRIZ (RF03, UC17)",
    response_model=Unidade,
    responses=respostas_erro(401, 403, 404, 422),
)
def alterar_unidade(id: Id, dados: UnidadeAlteracao, ator: SO_MATRIZ, ip: IP, sessao: Sessao) -> Unidade:
    return UnidadeService(sessao).alterar_unidade(ator, id, dados, ip)


@router.get(
    "/produtos",
    summary="Listar catálogo padrão — MATRIZ, GERENTE (RF04)",
    response_model=ListaProdutos,
    responses=respostas_erro(401, 403, 422),
)
def listar_produtos(
    ator: MATRIZ_OU_GERENTE, sessao: Sessao, limit: Limit = 20, offset: Offset = 0
) -> ListaProdutos:
    return UnidadeService(sessao).listar_produtos(limit, offset)


@router.post(
    "/produtos",
    summary="Cadastrar produto — MATRIZ (RF04, UC18)",
    status_code=status.HTTP_201_CREATED,
    response_model=Produto,
    responses=respostas_erro(401, 403, 409, 422),
)
def cadastrar_produto(dados: ProdutoEntrada, ator: SO_MATRIZ, ip: IP, sessao: Sessao) -> Produto:
    return UnidadeService(sessao).cadastrar_produto(ator, dados, ip)


@router.patch(
    "/produtos/{id}",
    summary="Alterar produto — MATRIZ (RF04, UC18)",
    response_model=Produto,
    responses=respostas_erro(401, 403, 404, 409, 422),
)
def alterar_produto(id: Id, dados: ProdutoAlteracao, ator: SO_MATRIZ, ip: IP, sessao: Sessao) -> Produto:
    return UnidadeService(sessao).alterar_produto(ator, id, dados, ip)


@router.get(
    "/unidades/{id}/cardapio",
    summary="Consultar cardápio vigente da unidade (RF08, UC01)",
    response_model=ListaItensCardapio,
    responses=respostas_erro(404, 422),
)
def consultar_cardapio(id: Id, sessao: Sessao) -> ListaItensCardapio:
    return UnidadeService(sessao).consultar_cardapio(id)


@router.put(
    "/unidades/{id}/cardapio/{produto_id}",
    summary="Definir preço e disponibilidade na unidade — GERENTE da unidade, MATRIZ (RF05, UC19)",
    response_model=ItemCardapio,
    responses=respostas_erro(401, 403, 404, 409, 422),
)
def definir_item_cardapio(
    id: Id, produto_id: ProdutoId, dados: ItemCardapioEntrada, ator: MATRIZ_OU_GERENTE, ip: IP, sessao: Sessao
) -> ItemCardapio:
    return UnidadeService(sessao).definir_item_cardapio(ator, id, produto_id, dados, ip)
