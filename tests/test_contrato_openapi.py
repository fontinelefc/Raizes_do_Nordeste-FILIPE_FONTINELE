"""Teste de contrato (D44): o OpenAPI gerado pelo FastAPI deve bater com docs/api/openapi.json.

Compara, operação por operação: existência (método + caminho), tags, códigos de
resposta, parâmetros de caminho e de consulta, presença de corpo e esquemas de
segurança. A comparação campo a campo dos schemas fica para a E17.
"""

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.main import criar_app
from app.nucleo.config import Config

RAIZ = Path(__file__).resolve().parents[1]
CONTRATO = json.loads((RAIZ / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
PREFIXO = urlparse(CONTRATO["servers"][0]["url"]).path  # /api/v1
METODOS = {"get", "post", "put", "patch", "delete"}


def _resolver(doc: dict, obj: dict) -> dict:
    """Segue um $ref local (#/components/...)."""
    if "$ref" not in obj:
        return obj
    alvo = doc
    for parte in obj["$ref"].lstrip("#/").split("/"):
        alvo = alvo[parte]
    return alvo


def _operacoes(doc: dict, prefixo: str = "") -> dict:
    seguranca_global = doc.get("security", [])
    ops = {}
    for caminho, item in doc["paths"].items():
        for metodo, op in item.items():
            if metodo not in METODOS:
                continue
            parametros = [_resolver(doc, p) for p in op.get("parameters", [])]
            seguranca = op.get("security", seguranca_global)
            ops[f"{metodo.upper()} {prefixo}{caminho}"] = {
                "tags": op.get("tags", []),
                "respostas": sorted(op["responses"]),
                "parametros": sorted((p["in"], p["name"]) for p in parametros if p["in"] in {"path", "query"}),
                "corpo": "requestBody" in op,
                # {} na lista = autenticação opcional; o FastAPI não expressa isso, então é ignorado
                "seguranca": sorted({nome for requisito in seguranca for nome in requisito}),
            }
    return ops


ESPERADO = _operacoes(CONTRATO, PREFIXO)
GERADO = _operacoes(criar_app(Config(gateway_simulado=True)).openapi())


def test_mesmas_operacoes():
    assert sorted(GERADO) == sorted(ESPERADO)
    assert len(GERADO) == 28


@pytest.mark.parametrize("operacao", sorted(ESPERADO))
def test_operacao_igual_ao_contrato(operacao):
    assert GERADO.get(operacao) == ESPERADO[operacao]


def test_gateway_simulado_desligado_por_padrao():
    gerado = _operacoes(criar_app(Config(gateway_simulado=False)).openapi())
    assert len(gerado) == 25
    assert not any("/gateway-simulado/" in op for op in gerado)


def test_esquemas_de_seguranca_declarados():
    gerado = criar_app(Config(gateway_simulado=True)).openapi()["components"]["securitySchemes"]
    assert set(gerado) == set(CONTRATO["components"]["securitySchemes"])
