"""E15 — Testes unitários das regras de negócio sem banco (RN01, RN05, RN07, RN08, RN10, RN14; D25, D31, D69, D70, D74).

Exercitam funções e tabelas puras dos services: horário da unidade, faixa de
preço, pontos e a tabela de transições do pedido. Rodam com o MySQL parado.
"""

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.enums import Canal, Perfil, StatusPedido
from app.models.unidade import Unidade
from app.nucleo.erros import ErroDominio
from app.services import pedidos
from app.services.fidelidade import pontos_do_valor
from app.services.unidades import UnidadeService, _conferir_faixa

S = StatusPedido
RECIFE = timezone(timedelta(hours=-3))  # America/Recife: UTC−3 o ano todo (D70)


def _unidade(abre: str, fecha: str, ativa: bool = True) -> Unidade:
    return Unidade(horario_abertura=time.fromisoformat(abre), horario_fechamento=time.fromisoformat(fecha), ativa=ativa)


def _as(hora: str) -> datetime:
    """Momento em UTC correspondente a ``hora`` em Recife, como o relógio da API entrega."""
    local = datetime.combine(datetime(2026, 11, 23).date(), time.fromisoformat(hora), RECIFE)
    return local.astimezone(timezone.utc)


# ---- RN05, D70: horário de funcionamento ----

@pytest.mark.parametrize(
    ("hora", "aberta"),
    [("05:59", False), ("06:00", True), ("12:00", True), ("21:59", True), ("22:00", False), ("23:30", False)],
)
def test_horario_comum_abre_na_hora_e_fecha_na_hora(hora, aberta):
    # Abertura incluída, fechamento excluído: às 22:00 a unidade já está fechada
    assert UnidadeService.esta_aberta(_unidade("06:00", "22:00"), _as(hora)) is aberta


@pytest.mark.parametrize(
    ("hora", "aberta"),
    [("17:59", False), ("18:00", True), ("23:59", True), ("00:00", True), ("01:59", True), ("02:00", False)],
)
def test_horario_que_passa_da_meia_noite(hora, aberta):
    assert UnidadeService.esta_aberta(_unidade("18:00", "02:00"), _as(hora)) is aberta


def test_hora_vem_do_fuso_de_recife_e_nao_do_utc():
    # 23:00 UTC = 20:00 em Recife: aberta, embora em UTC já tivesse passado das 22:00
    assert UnidadeService.esta_aberta(_unidade("06:00", "22:00"), datetime(2026, 11, 23, 23, 0, tzinfo=timezone.utc))
    # 08:30 UTC = 05:30 em Recife: fechada
    assert not UnidadeService.esta_aberta(_unidade("06:00", "22:00"), datetime(2026, 11, 23, 8, 30, tzinfo=timezone.utc))


def test_unidade_inativa_nunca_esta_aberta():
    assert not UnidadeService.esta_aberta(_unidade("00:00", "23:59", ativa=False), _as("12:00"))


# ---- RN01: faixa de preço do produto ----

@pytest.mark.parametrize(
    ("minimo", "base", "maximo"), [("10.00", "12.00", "15.00"), ("12.00", "12.00", "12.00"), ("0.01", "0.01", "9.99")]
)
def test_faixa_coerente_e_aceita(minimo, base, maximo):
    _conferir_faixa(Decimal(minimo), Decimal(base), Decimal(maximo))  # não lança


@pytest.mark.parametrize(
    ("minimo", "base", "maximo"),
    [("0.00", "5.00", "9.00"), ("10.00", "9.99", "15.00"), ("10.00", "15.01", "15.00"), ("16.00", "15.00", "14.00")],
    ids=["minimo_zero", "base_abaixo", "base_acima", "invertida"],
)
def test_faixa_incoerente_e_recusada(minimo, base, maximo):
    with pytest.raises(ErroDominio) as erro:
        _conferir_faixa(Decimal(minimo), Decimal(base), Decimal(maximo))
    assert erro.value.codigo == "VALIDACAO"
    assert erro.value.detalhes[0]["campo"] == "preco_base"


# ---- RN14, D74: pontos de fidelidade ----

@pytest.mark.parametrize(
    ("valor", "pontos"), [("0.99", 0), ("1.00", 1), ("37.90", 37), ("43.99", 43), ("100.00", 100), ("99999999.99", 99999999)]
)
def test_pontos_ignoram_os_centavos_sem_arredondar(valor, pontos):
    assert pontos_do_valor(Decimal(valor)) == pontos


# ---- RN07, RN08, D31, D69: tabela de transições do pedido ----

def test_avancos_manuais_seguem_t6_a_t8():
    assert pedidos.AVANCOS == {
        S.EM_PREPARO: (S.PAGO, Perfil.COZINHA),  # T6
        S.PRONTO: (S.EM_PREPARO, Perfil.COZINHA),  # T7
        S.ENTREGUE: (S.PRONTO, Perfil.ATENDENTE),  # T8
    }


def test_dono_cancela_so_antes_do_preparo_e_gerente_ate_pronto():
    assert pedidos.CANCELAVEIS_DONO == {S.AGUARDANDO_PAGAMENTO, S.PAGO}  # T5, T9
    assert pedidos.CANCELAVEIS_GERENTE == pedidos.CANCELAVEIS_DONO | {S.EM_PREPARO, S.PRONTO}  # T10, T11


def test_estados_finais_nao_saem_por_nenhuma_transicao_manual():
    finais = {S.ENTREGUE, S.PAGAMENTO_RECUSADO, S.EXPIRADO, S.CANCELADO}
    origens_manuais = {origem for origem, _ in pedidos.AVANCOS.values()} | pedidos.CANCELAVEIS_GERENTE
    assert finais.isdisjoint(origens_manuais)


def test_canais_por_quem_cria_o_pedido():
    # Balcão só pelo atendente (logado); totem só anônimo; o cliente logado usa app e pick-up
    assert Canal.BALCAO not in pedidos.CANAIS_ANONIMO | pedidos.CANAIS_CLIENTE
    assert pedidos.CANAIS_CLIENTE == {Canal.APP, Canal.PICKUP}
    assert Canal.TOTEM in pedidos.CANAIS_ANONIMO


def test_prazo_de_pagamento_e_de_15_minutos():
    assert pedidos.EXPIRACAO == timedelta(minutes=15)  # RN10, D08
