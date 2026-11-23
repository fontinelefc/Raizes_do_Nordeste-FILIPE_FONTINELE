"""Enumerações do domínio (seção 3.3 do doc; components/schemas do openapi.yaml).

São as 11 enumerações do modelo de dados (D30). Herdam de ``str`` para que o
valor gravado no MySQL e o valor trafegado no JSON sejam o mesmo texto.
"""

from enum import Enum


class Perfil(str, Enum):
    MATRIZ = "MATRIZ"
    GERENTE = "GERENTE"
    ATENDENTE = "ATENDENTE"
    COZINHA = "COZINHA"


class TipoOperacao(str, Enum):
    COMPLETA = "COMPLETA"
    REDUZIDA = "REDUZIDA"


class Canal(str, Enum):
    APP = "APP"
    TOTEM = "TOTEM"
    BALCAO = "BALCAO"
    PICKUP = "PICKUP"


class StatusPedido(str, Enum):
    """Estados da máquina do pedido (D07, D31)."""

    AGUARDANDO_PAGAMENTO = "AGUARDANDO_PAGAMENTO"
    PAGO = "PAGO"
    EM_PREPARO = "EM_PREPARO"
    PRONTO = "PRONTO"
    ENTREGUE = "ENTREGUE"
    PAGAMENTO_RECUSADO = "PAGAMENTO_RECUSADO"
    EXPIRADO = "EXPIRADO"
    CANCELADO = "CANCELADO"


class StatusPagamento(str, Enum):
    PENDENTE = "PENDENTE"
    APROVADO = "APROVADO"
    RECUSADO = "RECUSADO"
    ESTORNO_SOLICITADO = "ESTORNO_SOLICITADO"
    ESTORNADO = "ESTORNADO"


class TipoPagamento(str, Enum):
    ONLINE = "ONLINE"
    BALCAO = "BALCAO"


class FormaPagamento(str, Enum):
    PIX = "PIX"
    CARTAO_CREDITO = "CARTAO_CREDITO"
    CARTAO_DEBITO = "CARTAO_DEBITO"
    DINHEIRO = "DINHEIRO"


class OrigemAcao(str, Enum):
    CLIENTE = "CLIENTE"
    FUNCIONARIO = "FUNCIONARIO"
    SISTEMA = "SISTEMA"
    GATEWAY = "GATEWAY"


class Finalidade(str, Enum):
    FIDELIDADE = "FIDELIDADE"


class FaixaEtaria(str, Enum):
    """Faixa etária em vez de data de nascimento (D10, minimização LGPD)."""

    MENOR_18 = "MENOR_18"
    DE_18_A_24 = "DE_18_A_24"
    DE_25_A_34 = "DE_25_A_34"
    DE_35_A_44 = "DE_35_A_44"
    DE_45_A_59 = "DE_45_A_59"
    A_PARTIR_60 = "A_PARTIR_60"


class TipoMovPontos(str, Enum):
    CREDITO = "CREDITO"
    ESTORNO = "ESTORNO"
