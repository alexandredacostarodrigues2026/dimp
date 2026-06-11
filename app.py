from __future__ import annotations

import csv
import io
import logging
import os
from collections import Counter
from dataclasses import fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import streamlit as st

from processar_dimp import (
    EventoDimp,
    Registro1100,
    Registro1110,
    Registro1115,
    chave_1100,
    chave_1110,
    parse_dimp,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOG = logging.getLogger("dimp.app")

_ARQUIVO_EXEMPLO_PADRAO = (
    "DIMP_09_PB_22896431000382_2026-02-01_2026-02-28_1_1_W0118266_17-03-2026_183030_PICPAY-INSTITUICAO-DE-PAGAMENT.txt"
)
ARQUIVO_EXEMPLO = Path(os.environ.get("DIMP_ARQUIVO_EXEMPLO", _ARQUIVO_EXEMPLO_PADRAO))
REGISTROS_ALVO = ("0000", "0100", "0200", "1100", "1110", "1115")


def serializar_registro(evento: EventoDimp) -> dict[str, Any]:
    registro = evento.registro
    if is_dataclass(registro):
        dados = {
            f.name: str(getattr(registro, f.name))
            for f in fields(registro)
            if not is_dataclass(getattr(registro, f.name))
        }
        # Injeta chaves de ligação como FK explícita nos registros filhos
        if isinstance(registro, Registro1100):
            dados["chave_1100"] = chave_1100(registro)
        elif isinstance(registro, Registro1110):
            dados["chave_pai_1100"] = chave_1100(registro.pai_1100)
            dados["chave_1110"] = chave_1110(registro)
        elif isinstance(registro, Registro1115):
            dados["chave_pai_1110"] = chave_1110(registro.pai_1110)
            dados["chave_pai_1100"] = chave_1100(registro.pai_1110.pai_1100)
    else:
        dados = {"valor": str(registro)}

    return {"linha": evento.linha, "reg": evento.reg, **dados}


@st.cache_data(show_spinner=False)
def carregar_eventos(caminho: str, limite: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    contagem: Counter[str] = Counter()
    tabelas: dict[str, list[dict[str, Any]]] = {reg: [] for reg in REGISTROS_ALVO}

    for evento in parse_dimp(Path(caminho)):
        contagem[evento.reg] += 1
        if evento.reg in REGISTROS_ALVO and len(tabelas[evento.reg]) < limite:
            tabelas[evento.reg].append(serializar_registro(evento))

    return tabelas, dict(contagem)


def gerar_csv(linhas: list[dict[str, Any]]) -> bytes:
    if not linhas:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=linhas[0].keys())
    writer.writeheader()
    writer.writerows(linhas)
    return buf.getvalue().encode("utf-8-sig")


def caminho_origem() -> tuple[str, str]:
    arquivo = st.sidebar.file_uploader("Arquivo DIMP", type=("txt",), accept_multiple_files=False)
    if arquivo is None:
        return str(ARQUIVO_EXEMPLO), ARQUIVO_EXEMPLO.name

    with NamedTemporaryFile(delete=False, suffix=".txt") as temporario:
        temporario.write(arquivo.getbuffer())
        return temporario.name, arquivo.name


st.set_page_config(page_title="Consulta DIMP", layout="wide")

st.title("Consulta DIMP")

st.sidebar.header("Fonte")
caminho, nome_arquivo = caminho_origem()
limite = st.sidebar.slider("Amostras carregadas", min_value=100, max_value=5000, value=1000, step=100)

if not Path(caminho).exists():
    st.error(f"Arquivo nao encontrado: {nome_arquivo}")
    st.stop()

try:
    with st.spinner("Processando DIMP em streaming..."):
        tabelas, contagem = carregar_eventos(caminho, limite)
except Exception as exc:
    LOG.error("Falha ao processar %s: %s", nome_arquivo, exc, exc_info=True)
    st.error(f"Erro ao processar o arquivo: {exc}")
    st.stop()

total = sum(contagem.values())

col_arquivo, col_total, col_tipos = st.columns(3)
col_arquivo.metric("Arquivo", nome_arquivo)
col_total.metric("Registros DIMP", f"{total:,}".replace(",", "."))
col_tipos.metric("Tipos encontrados", len(contagem))

st.subheader("Contagem por registro")
contagem_ordenada = [{"reg": reg, "quantidade": qtd} for reg, qtd in sorted(contagem.items())]
st.dataframe(contagem_ordenada, use_container_width=True, hide_index=True)

st.subheader("Tabelas por registro")

DESCRICOES = {
    "0000": "Cabecalho",
    "0100": "Clientes",
    "0200": "Meios de Captura",
    "1100": "Resumo Mensal",
    "1110": "Resumo Diario",
    "1115": "Transacoes",
}

abas = st.tabs([f"{reg} — {DESCRICOES[reg]}" for reg in REGISTROS_ALVO])

for aba, reg in zip(abas, REGISTROS_ALVO):
    with aba:
        linhas = tabelas[reg]
        qtd_total = contagem.get(reg, 0)
        qtd_amostra = len(linhas)

        busca = st.text_input(
            "Buscar em qualquer campo",
            placeholder="Ex.: 000182880, PIX, 2,50",
            key=f"busca_{reg}",
        )

        if busca:
            termo = busca.casefold()
            linhas = [
                l for l in linhas
                if any(termo in str(v).casefold() for v in l.values())
            ]

        st.caption(
            f"Exibindo {len(linhas)} linha(s) — amostra de {qtd_amostra} de {qtd_total:,} registros no arquivo.".replace(",", ".")
        )
        st.dataframe(linhas, use_container_width=True, hide_index=True)

        csv_bytes = gerar_csv(tabelas[reg])
        st.download_button(
            label=f"Exportar {reg} como CSV",
            data=csv_bytes,
            file_name=f"dimp_{reg}.csv",
            mime="text/csv",
            key=f"export_{reg}",
        )
