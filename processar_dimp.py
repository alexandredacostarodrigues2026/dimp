from __future__ import annotations

import argparse
import io
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Generator, Iterable, Optional


LOG = logging.getLogger("dimp")

# P<numero>(AAAAMMDD)(HHMMSS)W  — string de protocolo TEF/TED
_RE_DT_TX_PROTOCOLO = re.compile(r"P\d*?(20\d{6})(\d{6})W")
_RE_DT_TX_HEADER    = re.compile(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}")
_RE_DT_TX_NOME      = re.compile(r"(\d{2})-(\d{2})-(\d{4})_(\d{6})")


def _extrair_dt_transmissao(caminho: Path) -> tuple[str, str]:
    """Retorna (dt_tx, hora_tx) no formato AAAAMMDD e HHMMSS.

    Prioridade:
    1. String de protocolo P...W no cabeçalho (mais precisa).
    2. Data formatada YYYY/MM/DD HH:MM:SS no cabeçalho.
    3. Padrão DD-MM-YYYY_HHMMSS no caminho do arquivo.
    """
    with io.open(caminho, mode="r", encoding="ISO-8859-1", errors="replace") as f:
        primeira_linha = f.readline()

    m = _RE_DT_TX_PROTOCOLO.search(primeira_linha)
    if m:
        return m.group(1), m.group(2)             # "20260511", "111331"

    m = _RE_DT_TX_HEADER.search(primeira_linha)
    if m:
        valor = m.group(0)                        # "2026/03/17 18:30:25"
        return valor[:10].replace("/", ""), valor[11:].replace(":", "")

    m = _RE_DT_TX_NOME.search(str(caminho))
    if m:
        dia, mes, ano, hora = m.group(1), m.group(2), m.group(3), m.group(4)
        return f"{ano}{mes}{dia}", hora

    return "", ""


def campo(campos: list[str], indice: int, padrao: str = "") -> str:
    if indice >= len(campos):
        return padrao
    return campos[indice].strip()


def decimal_br(valor: str) -> Decimal:
    valor = valor.strip()
    if not valor:
        return Decimal("0")
    try:
        return Decimal(valor.replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Valor decimal invalido: {valor!r}") from exc


def inteiro(valor: str) -> int:
    valor = valor.strip()
    if not valor:
        return 0
    return int(valor)


@dataclass(frozen=True)
class Registro00000:
    dt_tx: str
    hora_tx: str


@dataclass(frozen=True)
class Registro0000:
    versao: str
    finalidade: str
    uf: str
    cnpj_ip: str
    nome_ip: str
    dt_ini: str
    dt_fin: str
    situacao: str
    competencia: str

    @classmethod
    def from_campos(cls, campos: list[str]) -> "Registro0000":
        return cls(
            versao=campo(campos, 1),
            finalidade=campo(campos, 2),
            uf=campo(campos, 3),
            cnpj_ip=campo(campos, 4),
            nome_ip=campo(campos, 5),
            dt_ini=campo(campos, 6),
            dt_fin=campo(campos, 7),
            situacao=campo(campos, 8),
            competencia=campo(campos, 9),
        )


@dataclass(frozen=True)
class Registro0100:
    cod_cliente: str
    cnpj: str
    cpf: str
    nome_razao_social: str
    logradouro: str
    cep: str
    cod_municipio: str
    uf: str
    nome_contato: str
    telefone: str
    email: str
    dt_inicio: str
    flag: str

    @classmethod
    def from_campos(cls, campos: list[str]) -> "Registro0100":
        return cls(
            cod_cliente=campo(campos, 1),
            cnpj=campo(campos, 2),
            cpf=campo(campos, 3),
            nome_razao_social=campo(campos, 4),
            logradouro=campo(campos, 5),
            cep=campo(campos, 6),
            cod_municipio=campo(campos, 7),
            uf=campo(campos, 8),
            nome_contato=campo(campos, 9),
            telefone=campo(campos, 10),
            email=campo(campos, 11),
            dt_inicio=campo(campos, 12),
            flag=campo(campos, 13),
        )


@dataclass(frozen=True)
class Registro0200:
    cod_mcapt: str
    cod_ip: str
    tipo_tecnologia: str
    flag: str
    marca: str

    @classmethod
    def from_campos(cls, campos: list[str]) -> "Registro0200":
        return cls(
            cod_mcapt=campo(campos, 1),
            cod_ip=campo(campos, 2),
            tipo_tecnologia=campo(campos, 3),
            flag=campo(campos, 4),
            marca=campo(campos, 5),
        )


# Tecnologias que dispensam o limiar CPF (POS=1, Mobile=2, E-commerce=3, TEF=4)
TECNOLOGIAS_ISENTAS_LIMIAR: frozenset[str] = frozenset({"1", "2", "3", "4"})
LIMIAR_VALOR_CPF = Decimal("3375.00")
LIMIAR_QTD_CPF = 30


@dataclass(frozen=True)
class Registro1100:
    cod_ip_par: str
    cod_cliente: str
    ind_comex: str
    ind_extemp: str
    dt_ini: str
    dt_fin: str
    valor: Decimal
    qtd: int

    @classmethod
    def from_campos(cls, campos: list[str]) -> "Registro1100":
        return cls(
            cod_ip_par=campo(campos, 1),
            cod_cliente=campo(campos, 2),
            ind_comex=campo(campos, 3),
            ind_extemp=campo(campos, 4),
            dt_ini=campo(campos, 5),
            dt_fin=campo(campos, 6),
            valor=decimal_br(campo(campos, 7)),
            qtd=inteiro(campo(campos, 8)),
        )

    def validar_soma(self, soma_filhos: Decimal) -> Optional[str]:
        if soma_filhos != self.valor:
            return (
                f"Divergencia 1100 cod_cliente={self.cod_cliente}: "
                f"declarado={self.valor_formatado} soma_1110={soma_filhos}"
            )
        return None

    def alerta_limiar_cpf(self, cpf: str, tecnologias: frozenset) -> Optional[str]:
        if not cpf:
            return None
        if tecnologias & TECNOLOGIAS_ISENTAS_LIMIAR:
            return None
        if self.valor < LIMIAR_VALOR_CPF or self.qtd < LIMIAR_QTD_CPF:
            return (
                f"CPF {cpf} cod_cliente={self.cod_cliente}: "
                f"valor={self.valor_formatado} qtd={self.qtd} "
                f"abaixo do limiar (R$3.375,00 / 30 transacoes)"
            )
        return None

    @property
    def valor_formatado(self) -> str:
        inteiro_str, decimal_str = f"{self.valor:.2f}".split(".")
        return f"{inteiro_str},{decimal_str}"


@dataclass(frozen=True)
class Registro1110:
    cod_mcapt: str
    dt_operacao: str
    valor_total_diario: Decimal
    qtd_total: int
    cnpj_ip: str
    pai_1100: Registro1100

    @classmethod
    def from_campos(cls, campos: list[str], pai_1100: Registro1100) -> "Registro1110":
        return cls(
            cod_mcapt=campo(campos, 1),
            dt_operacao=campo(campos, 2),
            valor_total_diario=decimal_br(campo(campos, 3)),
            qtd_total=inteiro(campo(campos, 4)),
            cnpj_ip=campo(campos, 5),
            pai_1100=pai_1100,
        )


@dataclass(frozen=True)
class Registro1115:
    nsu: str
    cod_aut: str
    id_transac: str
    flag: str
    natureza_operacao: str
    hora: str
    valor_transacao: Decimal
    qtd: int
    pai_1110: Registro1110

    @classmethod
    def from_campos(cls, campos: list[str], pai_1110: Registro1110) -> "Registro1115":
        return cls(
            nsu=campo(campos, 1),
            cod_aut=campo(campos, 2),
            id_transac=campo(campos, 3),
            flag=campo(campos, 4),
            natureza_operacao=campo(campos, 5),
            hora=campo(campos, 6),
            valor_transacao=decimal_br(campo(campos, 7)),
            qtd=inteiro(campo(campos, 8)),
            pai_1110=pai_1110,
        )


def chave_00000(r: "Registro00000") -> str:
    return f"{r.dt_tx}|{r.hora_tx}"


def chave_1100(r: "Registro1100") -> str:
    return f"{r.cod_cliente}|{r.dt_ini}|{r.dt_fin}"


def chave_1110(r: "Registro1110") -> str:
    return f"{chave_1100(r.pai_1100)}|{r.cod_mcapt}|{r.dt_operacao}"


@dataclass(frozen=True)
class EventoDimp:
    linha: int
    reg: str
    registro: object


class EstadoDimp:
    def __init__(self) -> None:
        self.abertura: Optional[Registro0000] = None
        self.clientes: Dict[str, Registro0100] = {}
        self.meios_captura: Dict[str, Registro0200] = {}
        self.resumo_mensal_ativo: Optional[Registro1100] = None
        self.operacao_diaria_ativa: Optional[Registro1110] = None
        self.soma_1115_do_1110 = Decimal("0")
        self.soma_1110_do_1100 = Decimal("0")
        self.tecnologias_do_1100: set[str] = set()

    def fechar_1110(self) -> None:
        if self.operacao_diaria_ativa is None:
            return

        esperado = self.operacao_diaria_ativa.valor_total_diario
        if self.soma_1115_do_1110 != esperado:
            LOG.warning(
                "Divergencia 1110: cod_mcapt=%s dt=%s esperado=%s soma_1115=%s",
                self.operacao_diaria_ativa.cod_mcapt,
                self.operacao_diaria_ativa.dt_operacao,
                esperado,
                self.soma_1115_do_1110,
            )

        self.operacao_diaria_ativa = None
        self.soma_1115_do_1110 = Decimal("0")

    def fechar_1100(self) -> None:
        self.fechar_1110()
        if self.resumo_mensal_ativo is None:
            return

        r = self.resumo_mensal_ativo

        msg = r.validar_soma(self.soma_1110_do_1100)
        if msg:
            LOG.warning(msg)

        cliente = self.clientes.get(r.cod_cliente)
        cpf = cliente.cpf if cliente else ""
        techs = frozenset(self.tecnologias_do_1100)
        msg = r.alerta_limiar_cpf(cpf, techs)
        if msg:
            LOG.warning(msg)

        self.resumo_mensal_ativo = None
        self.soma_1110_do_1100 = Decimal("0")
        self.tecnologias_do_1100 = set()


def iter_linhas_dimp(caminho: Path) -> Generator[tuple[int, list[str]], None, None]:
    with io.open(caminho, mode="r", encoding="ISO-8859-1", errors="replace") as arquivo:
        for numero_linha, linha in enumerate(arquivo, start=1):
            texto = linha.strip()
            if not texto.startswith("|"):
                continue

            campos = texto.strip("|").split("|")
            if campos and campos[0]:
                yield numero_linha, campos


def parse_dimp(caminho: Path) -> Generator[EventoDimp, None, EstadoDimp]:
    estado = EstadoDimp()
    dt_tx, hora_tx = _extrair_dt_transmissao(caminho)
    emitiu_00000 = False

    for numero_linha, campos in iter_linhas_dimp(caminho):
        reg = campos[0]

        try:
            if reg == "00000":
                registro = Registro00000(dt_tx=campo(campos, 1), hora_tx=campo(campos, 2))
                yield EventoDimp(numero_linha, reg, registro)
                emitiu_00000 = True

            elif reg == "0000":
                if estado.abertura is not None:
                    continue  # ignora 0000 duplicado na secao de totais
                if not emitiu_00000:
                    yield EventoDimp(0, "00000", Registro00000(dt_tx=dt_tx, hora_tx=hora_tx))
                    emitiu_00000 = True
                estado.abertura = Registro0000.from_campos(campos)
                yield EventoDimp(numero_linha, reg, estado.abertura)

            elif reg == "0100":
                registro = Registro0100.from_campos(campos)
                estado.clientes[registro.cod_cliente] = registro
                yield EventoDimp(numero_linha, reg, registro)

            elif reg == "0200":
                registro = Registro0200.from_campos(campos)
                estado.meios_captura[registro.cod_mcapt] = registro
                yield EventoDimp(numero_linha, reg, registro)

            elif reg == "1100":
                estado.fechar_1100()
                registro = Registro1100.from_campos(campos)
                estado.resumo_mensal_ativo = registro
                yield EventoDimp(numero_linha, reg, registro)

            elif reg == "1110":
                estado.fechar_1110()
                if estado.resumo_mensal_ativo is None:
                    LOG.warning("Linha %s: registro 1110 sem pai 1100 ativo — ignorado", numero_linha)
                    continue
                registro = Registro1110.from_campos(campos, estado.resumo_mensal_ativo)
                estado.operacao_diaria_ativa = registro
                estado.soma_1110_do_1100 += registro.valor_total_diario
                mcapt = estado.meios_captura.get(registro.cod_mcapt)
                if mcapt:
                    estado.tecnologias_do_1100.add(mcapt.tipo_tecnologia)
                yield EventoDimp(numero_linha, reg, registro)

            elif reg == "1115":
                if estado.operacao_diaria_ativa is None:
                    LOG.warning("Linha %s: registro 1115 sem pai 1110 ativo — ignorado", numero_linha)
                    continue
                registro = Registro1115.from_campos(campos, estado.operacao_diaria_ativa)
                estado.soma_1115_do_1110 += registro.valor_transacao
                yield EventoDimp(numero_linha, reg, registro)

        except (ValueError, IndexError) as exc:
            LOG.warning("Linha %s REG %s ignorada: %s", numero_linha, reg, exc)

    estado.fechar_1100()
    return estado


def log_primeiro_de_cada_tipo(eventos: Iterable[EventoDimp]) -> None:
    vistos: set[str] = set()
    alvo = {"0000", "0100", "0200", "1100", "1110", "1115"}

    for evento in eventos:
        if evento.reg in alvo and evento.reg not in vistos:
            LOG.info("Linha %s REG %s: %s", evento.linha, evento.reg, evento.registro)
            vistos.add(evento.reg)

        if vistos == alvo:
            break


def main() -> int:
    parser = argparse.ArgumentParser(description="Parser streaming para arquivos DIMP.")
    parser.add_argument("arquivo", type=Path, help="Arquivo DIMP texto delimitado por pipe.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Nivel do log de processamento.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(levelname)s %(message)s")
    log_primeiro_de_cada_tipo(parse_dimp(args.arquivo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
