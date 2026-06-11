from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import streamlit as st

from processar_dimp import EventoDimp, parse_dimp


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
        # Expande apenas campos primitivos; pais (pai_1100, pai_1110) são
        # ignorados para evitar expansão recursiva de 3 níveis por linha.
        dados = {
            f.name: str(getattr(registro, f.name))
            for f in fields(registro)
            if not is_dataclass(getattr(registro, f.name))
        }
    else:
        dados = {"valor": str(registro)}

    return {"linha": evento.linha, "reg": evento.reg, **dados}


@st.cache_data(show_spinner=False)
def carregar_eventos(caminho: str, limite: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    contagem: Counter[str] = Counter()
    amostras: list[dict[str, Any]] = []

    for evento in parse_dimp(Path(caminho)):
        contagem[evento.reg] += 1
        if evento.reg in REGISTROS_ALVO and len(amostras) < limite:
            amostras.append(serializar_registro(evento))

    return amostras, dict(contagem)


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
        amostras, contagem = carregar_eventos(caminho, limite)
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

st.subheader("Primeira consulta")
col_reg, col_busca = st.columns([1, 2])
registro = col_reg.selectbox("Registro", ("Todos", *REGISTROS_ALVO), index=0)
busca = col_busca.text_input("Buscar em qualquer campo", placeholder="Ex.: 000182880, PIX, 2.50")

linhas = amostras
if registro != "Todos":
    linhas = [linha for linha in linhas if linha["reg"] == registro]

if busca:
    termo = busca.casefold()
    linhas = [
        linha
        for linha in linhas
        if any(termo in str(valor).casefold() for valor in linha.values())
    ]

st.caption(f"Exibindo {len(linhas)} linha(s) da amostra carregada de {len(amostras)} registro(s).")
st.dataframe(linhas, use_container_width=True, hide_index=True)

with st.expander("Contexto tecnico"):
    st.markdown(
        """
        - `0000` abre o arquivo e identifica a instituicao declarante.
        - `0100` cadastra clientes.
        - `0200` cadastra meios de captura.
        - `1100` resume o movimento mensal por cliente.
        - `1110` resume o movimento diario dentro do `1100`.
        - `1115` detalha transacoes e alimenta a validacao de soma do `1110`.
        """
    )
