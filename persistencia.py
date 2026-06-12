"""
Persistência DIMP V10 em SQLite.

Regras de negócio:
  Finalidade 1 (Normal)      — INSERT dos registros do arquivo (inclui IND_EXTEMP 0 e 1)
  Finalidade 2 (Retificação) — DELETE cirúrgico WHERE cnpj_ip + competencia + ind_extemp='0',
                               depois INSERT dos novos registros.
                               Registros com IND_EXTEMP='1' de envios anteriores são preservados.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from processar_dimp import (
    ErroRetificacao,
    Registro0000,
    Registro00000,
    Registro1100,
    Registro1110,
    Registro1115,
    chave_1100 as _chave_1100,
    chave_1110 as _chave_1110,
    parse_dimp,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS lote (
    chave_lote  TEXT PRIMARY KEY,          -- cnpj|dt_tx|hora_tx
    cnpj_ip     TEXT NOT NULL,
    competencia TEXT NOT NULL,
    finalidade  TEXT NOT NULL,
    dt_tx       TEXT NOT NULL,
    hora_tx     TEXT NOT NULL,
    criado_em   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reg_1100 (
    chave_1100  TEXT PRIMARY KEY,
    chave_lote  TEXT NOT NULL REFERENCES lote(chave_lote),
    cnpj_ip     TEXT NOT NULL,
    competencia TEXT NOT NULL,
    cod_cliente TEXT NOT NULL,
    ind_extemp  TEXT NOT NULL,
    dt_ini      TEXT NOT NULL,
    dt_fin      TEXT NOT NULL,
    valor       TEXT NOT NULL,
    qtd         INTEGER NOT NULL
);
-- Índice usado pelo DELETE cirúrgico em retificações
CREATE INDEX IF NOT EXISTS idx_1100_retificacao
    ON reg_1100 (cnpj_ip, competencia, ind_extemp);
CREATE INDEX IF NOT EXISTS idx_1100_lote
    ON reg_1100 (chave_lote);

CREATE TABLE IF NOT EXISTS reg_1110 (
    chave_1110      TEXT PRIMARY KEY,
    chave_pai_1100  TEXT NOT NULL REFERENCES reg_1100(chave_1100),
    chave_lote      TEXT NOT NULL,
    cod_mcapt       TEXT NOT NULL,
    dt_operacao     TEXT NOT NULL,
    valor_total     TEXT NOT NULL,
    qtd_total       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_1110_pai
    ON reg_1110 (chave_pai_1100);

CREATE TABLE IF NOT EXISTS reg_1115 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_pai_1110  TEXT NOT NULL REFERENCES reg_1110(chave_1110),
    chave_lote      TEXT NOT NULL,
    nsu             TEXT,
    cod_aut         TEXT,
    id_transac      TEXT,
    natureza        TEXT,
    hora            TEXT,
    valor           TEXT NOT NULL,
    qtd             INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_1115_pai
    ON reg_1115 (chave_pai_1110);
"""


def criar_banco(db_path: Path) -> None:
    """Cria o banco e aplica o schema (idempotente)."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_DDL)


# ---------------------------------------------------------------------------
# Operação atômica
# ---------------------------------------------------------------------------

def processar_lote(db_path: Path, caminho_dimp: Path) -> dict:
    """
    Processa um arquivo DIMP de forma atômica conforme a finalidade.

    Retorna:
        {"finalidade": str, "cnpj_ip": str, "competencia": str,
         "inseridos_1100": int, "inseridos_1110": int, "inseridos_1115": int,
         "deletados_1100": int}

    Lança:
        ErroRetificacao — se alguma regra V10 for violada (aborta sem gravar nada)
        ValueError      — se o arquivo não contiver registro 0000
    """
    criar_banco(db_path)

    # Coleta dados do parsing (ErroRetificacao propaga se violada)
    cabecalho_0000: Registro0000 | None = None
    cabecalho_00000: Registro00000 | None = None
    rows_1100: list[Registro1100] = []
    rows_1110: list[Registro1110] = []
    rows_1115: list[Registro1115] = []

    for ev in parse_dimp(caminho_dimp):
        if ev.reg == "00000":
            cabecalho_00000 = ev.registro  # type: ignore[assignment]
        elif ev.reg == "0000":
            cabecalho_0000 = ev.registro   # type: ignore[assignment]
        elif ev.reg == "1100":
            rows_1100.append(ev.registro)  # type: ignore[arg-type]
        elif ev.reg == "1110":
            rows_1110.append(ev.registro)  # type: ignore[arg-type]
        elif ev.reg == "1115":
            rows_1115.append(ev.registro)  # type: ignore[arg-type]

    if cabecalho_0000 is None:
        raise ValueError("Arquivo DIMP sem registro 0000 — impossivel persistir.")

    cnpj = cabecalho_0000.cnpj_ip
    competencia = cabecalho_0000.competencia
    finalidade = cabecalho_0000.finalidade
    dt_tx = cabecalho_00000.dt_tx if cabecalho_00000 else ""
    hora_tx = cabecalho_00000.hora_tx if cabecalho_00000 else ""
    chave_lote = f"{cnpj}|{dt_tx}|{hora_tx}"

    # Monta chave_tx para prefixar as chaves dos filhos
    chave_tx = chave_lote

    deletados = 0

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

        # --- Operação atômica ------------------------------------------------
        with conn:
            # Registra o lote
            conn.execute(
                "INSERT OR REPLACE INTO lote "
                "(chave_lote, cnpj_ip, competencia, finalidade, dt_tx, hora_tx) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chave_lote, cnpj, competencia, finalidade, dt_tx, hora_tx),
            )

            if finalidade == "2":
                # DELETE cirúrgico: remove apenas IND_EXTEMP='0' do período
                # Preserva IND_EXTEMP='1' (extemporâneos de envios anteriores)
                cur = conn.execute(
                    "DELETE FROM reg_1100 "
                    "WHERE cnpj_ip = ? AND competencia = ? AND ind_extemp = '0'",
                    (cnpj, competencia),
                )
                deletados = cur.rowcount

            # INSERT 1100
            conn.executemany(
                "INSERT OR REPLACE INTO reg_1100 "
                "(chave_1100, chave_lote, cnpj_ip, competencia, cod_cliente, "
                " ind_extemp, dt_ini, dt_fin, valor, qtd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"{chave_tx}|{_chave_1100(r)}",
                        chave_lote, cnpj, competencia,
                        r.cod_cliente, r.ind_extemp,
                        r.dt_ini, r.dt_fin,
                        str(r.valor), r.qtd,
                    )
                    for r in rows_1100
                ],
            )

            # INSERT 1110
            conn.executemany(
                "INSERT OR REPLACE INTO reg_1110 "
                "(chave_1110, chave_pai_1100, chave_lote, cod_mcapt, "
                " dt_operacao, valor_total, qtd_total) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"{chave_tx}|{_chave_1110(r)}",
                        f"{chave_tx}|{_chave_1100(r.pai_1100)}",
                        chave_lote,
                        r.cod_mcapt, r.dt_operacao,
                        str(r.valor_total_diario), r.qtd_total,
                    )
                    for r in rows_1110
                ],
            )

            # INSERT 1115
            conn.executemany(
                "INSERT INTO reg_1115 "
                "(chave_pai_1110, chave_lote, nsu, cod_aut, id_transac, "
                " natureza, hora, valor, qtd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"{chave_tx}|{_chave_1110(r.pai_1110)}",
                        chave_lote,
                        r.nsu, r.cod_aut, r.id_transac,
                        r.natureza_operacao, r.hora,
                        str(r.valor_transacao), r.qtd,
                    )
                    for r in rows_1115
                ],
            )

    return {
        "finalidade": finalidade,
        "cnpj_ip": cnpj,
        "competencia": competencia,
        "chave_lote": chave_lote,
        "inseridos_1100": len(rows_1100),
        "inseridos_1110": len(rows_1110),
        "inseridos_1115": len(rows_1115),
        "deletados_1100": deletados,
    }
