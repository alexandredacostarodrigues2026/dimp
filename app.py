from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import zipfile
from collections import Counter
from dataclasses import fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import streamlit as st

from processar_dimp import (
    EventoDimp,
    Registro00000,
    Registro0000,
    Registro0100,
    Registro0200,
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

# Lookups estáticos — espelham lkp_* do banco (DIMP V10 / RCAD V06)
_NAT_OPER: dict[str, str] = {
    "1":  "Cartão de Crédito",
    "2":  "Cartão de Débito",
    "3":  "Boleto próprio",
    "4":  "Transferência",
    "5":  "Dinheiro / outra estrutura",
    "6":  "PIX",
    "7":  "Voucher / pré-pago",
    "8":  "Saque / troco / PIX Saque",
    "11": "Recepção de boletos / recargas",
    "12": "PIX Garantido",
}
_IND_SPLIT:    dict[str, str] = {"0": "Não splitado", "1": "Splitado"}
_IND_NAT_JUR:  dict[str, str] = {"0": "CPF (PF)", "1": "CNPJ (PJ)"}
_IND_TP_PIX:   dict[str, str] = {"0": "Dinâmico",  "1": "Não Dinâmico"}

_ARQUIVO_EXEMPLO_PADRAO = (
    "DIMP_09_PB_22896431000382_2026-02-01_2026-02-28_1_1_W0118266_17-03-2026_183030_PICPAY-INSTITUICAO-DE-PAGAMENT.txt"
)
ARQUIVO_EXEMPLO = Path(os.environ.get("DIMP_ARQUIVO_EXEMPLO", _ARQUIVO_EXEMPLO_PADRAO))
REGISTROS_ALVO = ("00000", "0000", "0100", "0200", "1100", "1110", "1115")


def serializar_registro(
    evento: EventoDimp,
    chave_tx: str = "",    # cnpj_ip|dt_tx|hora_tx — chave composta de transmissão
) -> dict[str, Any]:
    registro = evento.registro
    if is_dataclass(registro):
        dados = {
            f.name: str(getattr(registro, f.name))
            for f in fields(registro)
            if not is_dataclass(getattr(registro, f.name))
        }
        if isinstance(registro, Registro00000):
            dados["chave_00000"] = chave_tx             # cnpj|dt_tx|hora_tx
        elif isinstance(registro, Registro0000):
            dados["chave_pai_00000"] = chave_tx         # FK → 00000
            dados["chave_0000"] = chave_tx              # PK: cnpj|dt_tx|hora_tx
        elif isinstance(registro, (Registro0100, Registro0200)):
            dados["chave_pai_0000"] = chave_tx          # cnpj|dt_tx|hora_tx
        elif isinstance(registro, Registro1100):
            dados["chave_pai_0000"] = chave_tx
            dados["chave_1100"] = f"{chave_tx}|{chave_1100(registro)}"
        elif isinstance(registro, Registro1110):
            dados["chave_pai_0000"] = chave_tx
            dados["chave_pai_1100"] = f"{chave_tx}|{chave_1100(registro.pai_1100)}"
            dados["chave_1110"] = f"{chave_tx}|{chave_1110(registro)}"
        elif isinstance(registro, Registro1115):
            dados["chave_pai_0000"] = chave_tx
            dados["chave_pai_1110"] = f"{chave_tx}|{chave_1110(registro.pai_1110)}"
            dados["chave_pai_1100"] = f"{chave_tx}|{chave_1100(registro.pai_1110.pai_1100)}"
            dados["nat_oper_desc"]   = _NAT_OPER.get(registro.nat_oper, registro.nat_oper)
            dados["ind_split_desc"]  = _IND_SPLIT.get(registro.ind_split, registro.ind_split)
            if registro.ind_nat_jur:
                dados["ind_nat_jur_desc"] = _IND_NAT_JUR.get(registro.ind_nat_jur, registro.ind_nat_jur)
            if registro.ind_tp_pix:
                dados["ind_tp_pix_desc"] = _IND_TP_PIX.get(registro.ind_tp_pix, registro.ind_tp_pix)
    else:
        dados = {"valor": str(registro)}

    return {"linha": evento.linha, "reg": evento.reg, **dados}


@st.cache_data(show_spinner=False)
def carregar_eventos(caminho: str, limite: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    contagem: Counter[str] = Counter()
    tabelas: dict[str, list[dict[str, Any]]] = {reg: [] for reg in REGISTROS_ALVO}
    chave_tx_ativa = ""  # cnpj|dt_tx|hora_tx — definida quando 0000 é lido
    pendente_00000: dict[str, Any] | None = None  # row do 00000 aguarda cnpj do 0000

    for evento in parse_dimp(Path(caminho)):
        contagem[evento.reg] += 1

        if evento.reg == "00000":
            # Armazena dt_tx|hora_tx provisório; cnpj será prefixado quando 0000 chegar
            row = serializar_registro(evento, "")
            chave_tx_ativa = f"{evento.registro.dt_tx}|{evento.registro.hora_tx}"  # type: ignore[union-attr]
            pendente_00000 = row

        elif evento.reg == "0000":
            cnpj = evento.registro.cnpj_ip  # type: ignore[union-attr]
            chave_tx_ativa = f"{cnpj}|{chave_tx_ativa}"
            # Finaliza 00000 com a chave completa e anexa
            if pendente_00000 is not None:
                pendente_00000["chave_00000"] = chave_tx_ativa
                if len(tabelas["00000"]) < limite:
                    tabelas["00000"].append(pendente_00000)
                pendente_00000 = None
            # Serializa 0000 com chave_tx já completa
            if len(tabelas["0000"]) < limite:
                tabelas["0000"].append(serializar_registro(evento, chave_tx_ativa))

        elif evento.reg in REGISTROS_ALVO and len(tabelas[evento.reg]) < limite:
            tabelas[evento.reg].append(serializar_registro(evento, chave_tx_ativa))

    return tabelas, dict(contagem)


def gerar_csv(linhas: list[dict[str, Any]]) -> bytes:
    if not linhas:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=linhas[0].keys())
    writer.writeheader()
    writer.writerows(linhas)
    return buf.getvalue().encode("utf-8-sig")


@st.cache_data(show_spinner=False)
def gerar_comparacao(caminho: str) -> tuple[list[dict], list[dict]]:
    """Passagem completa no arquivo comparando valores declarados vs soma dos filhos."""
    from decimal import Decimal as _D

    def _fmt(v: _D) -> str:
        inteiro, dec = f"{v:.2f}".split(".")
        return f"{int(inteiro):,}".replace(",", ".") + f",{dec}"

    comp_1100: dict[str, dict] = {}
    comp_1110: dict[str, dict] = {}
    chave_tx = ""

    for ev in parse_dimp(Path(caminho)):
        if ev.reg == "00000":
            chave_tx = f"{ev.registro.dt_tx}|{ev.registro.hora_tx}"  # type: ignore[union-attr]
        elif ev.reg == "0000":
            chave_tx = f"{ev.registro.cnpj_ip}|{chave_tx}"           # type: ignore[union-attr]
        elif ev.reg == "1100":
            k = f"{chave_tx}|{chave_1100(ev.registro)}"
            comp_1100[k] = {
                "cod_cliente": ev.registro.cod_cliente,
                "declarado": ev.registro.valor,
                "soma_1110": _D("0"),
            }
        elif ev.reg == "1110":
            k_pai = f"{chave_tx}|{chave_1100(ev.registro.pai_1100)}"
            k = f"{chave_tx}|{chave_1110(ev.registro)}"
            if k_pai in comp_1100:
                comp_1100[k_pai]["soma_1110"] += ev.registro.valor_total_diario
            comp_1110[k] = {
                "cod_cliente": ev.registro.pai_1100.cod_cliente,
                "cod_mcapt": ev.registro.cod_mcapt,
                "dt_operacao": ev.registro.dt_operacao,
                "declarado": ev.registro.valor_total_diario,
                "soma_1115": _D("0"),
            }
        elif ev.reg == "1115":
            k_pai = f"{chave_tx}|{chave_1110(ev.registro.pai_1110)}"
            if k_pai in comp_1110:
                comp_1110[k_pai]["soma_1115"] += ev.registro.valor_transacao

    linhas_1100 = []
    for d in comp_1100.values():
        dif = d["declarado"] - d["soma_1110"]
        linhas_1100.append({
            "cod_cliente": d["cod_cliente"],
            "1100_declarado": _fmt(d["declarado"]),
            "soma_1110": _fmt(d["soma_1110"]),
            "diferenca": _fmt(dif),
            "status": "OK" if dif == 0 else "DIVERGENTE",
        })

    linhas_1110 = []
    for d in comp_1110.values():
        dif = d["declarado"] - d["soma_1115"]
        linhas_1110.append({
            "cod_cliente": d["cod_cliente"],
            "cod_mcapt": d["cod_mcapt"],
            "dt_operacao": d["dt_operacao"],
            "1110_declarado": _fmt(d["declarado"]),
            "soma_1115": _fmt(d["soma_1115"]),
            "diferenca": _fmt(dif),
            "status": "OK" if dif == 0 else "DIVERGENTE",
        })

    return linhas_1100, linhas_1110


PASTA_ORIGINAIS = Path("originais")
PASTA_EXTRAIDOS = Path("extraidos")


def _extrair_zip_para_pasta(caminho_zip: Path) -> tuple[Path, list[str]]:
    pasta = PASTA_EXTRAIDOS / caminho_zip.stem
    pasta.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(caminho_zip) as z:
        z.extractall(pasta)
        nomes = z.namelist()
        txts = sorted(
            [i for i in z.infolist() if i.filename.lower().endswith(".txt")],
            key=lambda i: i.file_size,
            reverse=True,
        )
        if not txts:
            raise ValueError("Nenhum arquivo .txt encontrado no ZIP.")
        nome_dimp = txts[0].filename

        elps = [i for i in z.infolist() if i.filename.lower().endswith(".elp")]
        if elps:
            cabecalho_bytes = z.read(elps[0].filename)
            cabecalho_txt = cabecalho_bytes.decode("iso-8859-1", errors="replace")

            m = re.search(r"P\d*?(20\d{6})(\d{6})W", cabecalho_txt)
            linha_00000 = (
                f"|00000|{m.group(1)}|{m.group(2)}|\n".encode("iso-8859-1")
                if m else b""
            )

            caminho_dimp = pasta / nome_dimp
            conteudo_dimp = caminho_dimp.read_bytes()
            if not conteudo_dimp.startswith(cabecalho_bytes[:10]):
                caminho_dimp.write_bytes(cabecalho_bytes + linha_00000 + conteudo_dimp)

    caminho_final = pasta / nome_dimp
    shutil.copy2(caminho_final, PASTA_EXTRAIDOS / caminho_final.name)
    return caminho_final, nomes


def _listar_zips() -> list[Path]:
    if not PASTA_ORIGINAIS.exists():
        return []
    return sorted(PASTA_ORIGINAIS.glob("*.zip"))


def _listar_extraidos() -> list[Path]:
    if not PASTA_EXTRAIDOS.exists():
        return []
    return sorted(
        p for p in PASTA_EXTRAIDOS.glob("*.txt")
        if p.stat().st_size > 10_000
    )


def sidebar_extracao() -> None:
    st.sidebar.header("Extração de ZIP")
    zips = _listar_zips()

    if not zips:
        st.sidebar.caption("Nenhum ZIP encontrado em originais/")
        return

    opcoes = {z.name: z for z in zips}
    selecionado = st.sidebar.selectbox("ZIP disponível", list(opcoes.keys()), label_visibility="collapsed")

    if st.sidebar.button("Extrair", use_container_width=True):
        try:
            caminho_dimp, arquivos = _extrair_zip_para_pasta(opcoes[selecionado])
            st.sidebar.success(f"Extraído em extraidos/{opcoes[selecionado].stem}/")
            for arq in arquivos:
                st.sidebar.caption(f"• {arq}")
        except Exception as exc:
            st.sidebar.error(str(exc))


def caminho_origem() -> tuple[str, str]:
    st.sidebar.header("Fonte de dados")

    extraidos = _listar_extraidos()
    opcoes_extraidos = {p.name: p for p in extraidos}

    modo = st.sidebar.radio(
        "Origem",
        ["Arquivo extraído", "Upload"],
        label_visibility="collapsed",
    )

    if modo == "Arquivo extraído":
        if not opcoes_extraidos:
            st.sidebar.caption("Nenhum arquivo extraído ainda. Use o painel acima.")
            return str(ARQUIVO_EXEMPLO), ARQUIVO_EXEMPLO.name
        nome = st.sidebar.selectbox("Arquivo", list(opcoes_extraidos.keys()), label_visibility="collapsed")
        p = opcoes_extraidos[nome]
        return str(p), nome

    arquivo = st.sidebar.file_uploader("Arquivo DIMP", type=("txt", "zip"), accept_multiple_files=False)
    if arquivo is None:
        return str(ARQUIVO_EXEMPLO), ARQUIVO_EXEMPLO.name

    dados = bytes(arquivo.getbuffer())
    nome = arquivo.name

    if nome.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(dados)) as z:
                txts = sorted(
                    [i for i in z.infolist() if i.filename.lower().endswith(".txt")],
                    key=lambda i: i.file_size, reverse=True,
                )
                if not txts:
                    raise ValueError("Nenhum .txt no ZIP.")
                conteudo = z.read(txts[0].filename)
                nome = f"{nome} → {txts[0].filename}"
            dados = conteudo
        except Exception as exc:
            st.error(f"Erro ao ler ZIP: {exc}")
            st.stop()

    with NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        tmp.write(dados)
        return tmp.name, nome


st.set_page_config(page_title="Consulta DIMP", layout="wide")

st.title("Consulta DIMP")

sidebar_extracao()
st.sidebar.divider()
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
    "00000": "Transmissao",
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

        if reg == "1115" and tabelas["1115"]:
            from decimal import Decimal as _D, InvalidOperation as _IE
            def _dec(v: str) -> _D:
                try:
                    return _D(str(v).replace(",", ".").replace(".", "", str(v).count(".") - 1)) if "," in str(v) else _D(str(v))
                except _IE:
                    return _D("0")

            acum: dict[str, dict] = {}
            for row in tabelas["1115"]:
                cod = str(row.get("nat_oper", ""))
                desc = str(row.get("nat_oper_desc", cod))
                if cod not in acum:
                    acum[cod] = {"nat_oper": cod, "descricao": desc, "qtd": 0, "valor_total": _D("0")}
                acum[cod]["qtd"] += 1
                acum[cod]["valor_total"] += _dec(row.get("valor_transacao", "0"))

            resumo = sorted(acum.values(), key=lambda r: int(r["nat_oper"]) if r["nat_oper"].isdigit() else 99)
            for r in resumo:
                r["valor_total"] = f"{r['valor_total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            with st.expander("Resumo por Natureza de Operação (amostra)"):
                st.caption("Baseado na amostra carregada — não representa o total do arquivo.")
                st.dataframe(resumo, use_container_width=True, hide_index=True)

        csv_bytes = gerar_csv(tabelas[reg])
        st.download_button(
            label=f"Exportar {reg} como CSV",
            data=csv_bytes,
            file_name=f"dimp_{reg}.csv",
            mime="text/csv",
            key=f"export_{reg}",
        )

st.divider()
st.subheader("Comparação de Valores")

try:
    with st.spinner("Calculando comparação..."):
        comp_1100, comp_1110 = gerar_comparacao(caminho)

    div_1100 = sum(1 for r in comp_1100 if r["status"] == "DIVERGENTE")
    div_1110 = sum(1 for r in comp_1110 if r["status"] == "DIVERGENTE")

    col_c1, col_c2 = st.columns(2)
    col_c1.metric("Divergências 1100 vs soma 1110", div_1100,
                  delta=None if div_1100 == 0 else f"{div_1100} clientes",
                  delta_color="inverse")
    col_c2.metric("Divergências 1110 vs soma 1115", div_1110,
                  delta=None if div_1110 == 0 else f"{div_1110} operações",
                  delta_color="inverse")

    with st.expander(f"1100 vs soma 1110 — {len(comp_1100)} clientes"):
        st.dataframe(comp_1100, use_container_width=True, hide_index=True)
        st.download_button("Exportar CSV", gerar_csv(comp_1100),
                           "comparacao_1100.csv", "text/csv", key="exp_comp_1100")

    with st.expander(f"1110 vs soma 1115 — {len(comp_1110)} operações diárias"):
        st.dataframe(comp_1110, use_container_width=True, hide_index=True)
        st.download_button("Exportar CSV", gerar_csv(comp_1110),
                           "comparacao_1110.csv", "text/csv", key="exp_comp_1110")

except Exception as exc:
    st.error(f"Erro ao gerar comparação: {exc}")
