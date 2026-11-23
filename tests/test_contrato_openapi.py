"""Teste de contrato (D44): o OpenAPI gerado pelo FastAPI deve bater com docs/api/openapi.json.

Compara, operação por operação: existência (método + caminho), tags, códigos de
resposta, parâmetros de caminho e de consulta, presença de corpo e esquemas de
segurança. Desde a E17, compara também os schemas campo a campo: o corpo da
requisição, o corpo de cada resposta e os cabeçalhos de resposta.

O contrato está em OpenAPI 3.0.3 e o FastAPI gera 3.1. Antes de comparar, os dois
lados passam por ``_canonico``, que segue os ``$ref``, junta os ``allOf`` e escreve
"pode ser nulo" de um jeito só (``nullable: true`` no 3.0.3; ``anyOf`` com
``type: null`` no 3.1). Nome de schema, título, descrição e exemplo não entram.
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


# ---- E17: schemas campo a campo ----

ATRIBUTOS = ["type", "format", "pattern", "enum", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"]


def _seguir(doc: dict, schema: dict) -> dict:
    """Segue os $ref, mantendo as chaves escritas ao lado do $ref (ex.: nullable)."""
    while "$ref" in schema:
        extra = {k: v for k, v in schema.items() if k != "$ref"}
        schema = {**_resolver(doc, {"$ref": schema["$ref"]}), **extra}
    return schema


def _canonico(doc: dict, schema: dict | None) -> dict:
    """Forma única do schema: tipo, restrições, campos, obrigatórios, extras e nulo."""
    schema = _seguir(doc, schema or {})
    nulo = bool(schema.get("nullable"))
    if "allOf" in schema:  # 3.0.3: composição (Unidade, Produto, PedidoDetalhe) ou $ref com nullable
        partes = [_canonico(doc, p) for p in schema["allOf"]]
        partes.append(_canonico(doc, {k: v for k, v in schema.items() if k != "allOf"}))
        junto: dict = {"nullable": False}
        for parte in partes:
            for chave, valor in parte.items():
                if chave == "properties":
                    junto.setdefault("properties", {}).update(valor)
                elif chave == "required":
                    junto["required"] = sorted(set(junto.get("required", [])) | set(valor))
                elif chave == "nullable":
                    junto["nullable"] = junto["nullable"] or valor
                else:
                    junto[chave] = valor
        return junto
    if "anyOf" in schema:  # 3.1: "X ou null"
        opcoes = [_seguir(doc, o) for o in schema["anyOf"]]
        nao_nulas = [o for o in opcoes if o.get("type") != "null"]
        assert len(nao_nulas) == 1, f"anyOf sem equivalente no contrato: {schema}"
        canonico = _canonico(doc, {**nao_nulas[0], **{k: schema[k] for k in ATRIBUTOS if k in schema}})
        canonico["nullable"] = len(nao_nulas) < len(opcoes) or canonico["nullable"]
        return canonico
    canonico: dict = {k: schema[k] for k in ATRIBUTOS if k in schema}
    if "enum" in canonico:
        canonico["enum"] = sorted(e for e in canonico["enum"] if e is not None)
    if "properties" in schema:
        canonico["type"] = "object"
        canonico["properties"] = {nome: _canonico(doc, p) for nome, p in schema["properties"].items()}
    if "required" in schema:
        canonico["required"] = sorted(schema["required"])
    if "additionalProperties" in schema:
        canonico["additionalProperties"] = schema["additionalProperties"]
    if "items" in schema:
        canonico["items"] = _canonico(doc, schema["items"])
    canonico["nullable"] = nulo
    return canonico


def _schemas(doc: dict, prefixo: str = "") -> dict:
    """{"MÉTODO /caminho → parte": schema canônico}; parte = corpo, resposta NNN ou cabeçalho NNN Nome."""
    saida = {}
    for caminho, item in doc["paths"].items():
        for metodo, op in item.items():
            if metodo not in METODOS:
                continue
            nome = f"{metodo.upper()} {prefixo}{caminho}"
            if "requestBody" in op:
                for tipo, conteudo in _resolver(doc, op["requestBody"])["content"].items():
                    saida[f"{nome} → corpo {tipo}"] = _canonico(doc, conteudo.get("schema"))
            for status, resposta in op["responses"].items():
                resposta = _resolver(doc, resposta)
                for tipo, conteudo in resposta.get("content", {}).items():
                    saida[f"{nome} → resposta {status} {tipo}"] = _canonico(doc, conteudo.get("schema"))
                for cabecalho, definicao in resposta.get("headers", {}).items():
                    saida[f"{nome} → cabeçalho {status} {cabecalho}"] = _canonico(doc, definicao.get("schema"))
    return saida


SCHEMAS_ESPERADOS = _schemas(CONTRATO, PREFIXO)
SCHEMAS_GERADOS = _schemas(criar_app(Config(gateway_simulado=True)).openapi())


def test_mesmas_partes_com_schema():
    """Mesmo conjunto de corpos, respostas com corpo e cabeçalhos nas 28 operações."""
    assert sorted(SCHEMAS_GERADOS) == sorted(SCHEMAS_ESPERADOS)


@pytest.mark.parametrize("parte", sorted(SCHEMAS_ESPERADOS))
def test_schema_igual_ao_contrato(parte):
    assert SCHEMAS_GERADOS.get(parte) == SCHEMAS_ESPERADOS[parte]
