from __future__ import annotations

import argparse
import io
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Generator, Iterable, Optional


LOG = logging.getLogger("dimp")


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


@dataclass(frozen=True)
class Registro1100:
    cod_cliente: str
    dt_ini: str
    dt_fin: str
    valor_total_mensal: Decimal
    qtd_total: int

    @classmethod
    def from_campos(cls, campos: list[str]) -> "Registro1100":
        return cls(
            cod_cliente=campo(campos, 2),
            dt_ini=campo(campos, 5),
            dt_fin=campo(campos, 6),
            valor_total_mensal=decimal_br(campo(campos, 7)),
            qtd_total=inteiro(campo(campos, 8)),
        )


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

        esperado = self.resumo_mensal_ativo.valor_total_mensal
        if self.soma_1110_do_1100 != esperado:
            LOG.warning(
                "Divergencia 1100: cod_cliente=%s esperado=%s soma_1110=%s",
                self.resumo_mensal_ativo.cod_cliente,
                esperado,
                self.soma_1110_do_1100,
            )

        self.resumo_mensal_ativo = None
        self.soma_1110_do_1100 = Decimal("0")


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

    for numero_linha, campos in iter_linhas_dimp(caminho):
        reg = campos[0]

        try:
            if reg == "0000":
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
