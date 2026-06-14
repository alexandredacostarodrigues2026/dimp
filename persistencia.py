"""
Persistência DIMP V10 em SQLite.

Regras de negócio:
  Finalidade 1 (Normal)      — INSERT dos registros do arquivo (inclui IND_EXTEMP 0 e 1)
  Finalidade 2 (Retificação) — DELETE cirúrgico WHERE cnpj_ip + dt_ini + dt_fin + ind_extemp='0',
                               depois INSERT dos novos registros.
                               Registros com IND_EXTEMP='1' de envios anteriores são preservados.
                               Período determinado por dt_ini + dt_fin (AAAAMMDD), não por competencia,
                               para cobrir declarações extemporâneas onde competencia ≠ mês dos dados.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from processar_dimp import (
    ErroRetificacao,
    Registro0000,
    Registro00000,
    Registro0100,
    Registro0200,
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
    dt_ini      TEXT NOT NULL,             -- período declarado (AAAAMMDD) — chave de período
    dt_fin      TEXT NOT NULL,             -- período declarado (AAAAMMDD) — chave de período
    criado_em   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reg_0100 (
    chave_0100        TEXT PRIMARY KEY,   -- chave_lote|cod_cliente
    chave_lote        TEXT NOT NULL REFERENCES lote(chave_lote),
    cnpj_ip           TEXT NOT NULL,
    cod_cliente       TEXT NOT NULL,
    cnpj              TEXT,
    cpf               TEXT,
    nome_razao_social TEXT,
    uf                TEXT
);
CREATE INDEX IF NOT EXISTS idx_0100_cliente
    ON reg_0100 (cnpj_ip, cod_cliente);

CREATE TABLE IF NOT EXISTS reg_0200 (
    chave_0200      TEXT PRIMARY KEY,   -- chave_lote|cod_mcapt
    chave_lote      TEXT NOT NULL REFERENCES lote(chave_lote),
    cnpj_ip         TEXT NOT NULL,
    cod_mcapt       TEXT NOT NULL,
    cod_ip          TEXT,
    tipo_tecnologia TEXT NOT NULL,
    marca           TEXT
);
CREATE INDEX IF NOT EXISTS idx_0200_mcapt
    ON reg_0200 (cnpj_ip, cod_mcapt);

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
-- Índice usado pelo DELETE cirúrgico em retificações (período = dt_ini + dt_fin)
CREATE INDEX IF NOT EXISTS idx_1100_retificacao
    ON reg_1100 (cnpj_ip, dt_ini, dt_fin, ind_extemp);
CREATE INDEX IF NOT EXISTS idx_1100_lote
    ON reg_1100 (chave_lote);

CREATE TABLE IF NOT EXISTS reg_1110 (
    chave_1110      TEXT PRIMARY KEY,
    chave_pai_1100  TEXT NOT NULL REFERENCES reg_1100(chave_1100) ON DELETE CASCADE,
    chave_lote      TEXT NOT NULL,
    cod_mcapt       TEXT NOT NULL,
    dt_operacao     TEXT NOT NULL,
    valor_total     TEXT NOT NULL,
    qtd_total       INTEGER NOT NULL,
    cnpj_liq        TEXT
);
CREATE INDEX IF NOT EXISTS idx_1110_pai
    ON reg_1110 (chave_pai_1100);

CREATE TABLE IF NOT EXISTS reg_1115 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_pai_1110  TEXT NOT NULL REFERENCES reg_1110(chave_1110) ON DELETE CASCADE,
    chave_lote      TEXT NOT NULL,
    nsu             TEXT,
    cod_aut         TEXT,
    id_transac      TEXT,
    ind_split       TEXT NOT NULL DEFAULT '0',
    bandeira        TEXT,
    hora            TEXT,
    valor           TEXT NOT NULL,
    nat_oper        TEXT NOT NULL,
    geo             TEXT,
    ind_nat_jur     TEXT,
    ind_tp_pix      TEXT
);
CREATE INDEX IF NOT EXISTS idx_1115_pai
    ON reg_1115 (chave_pai_1110);
CREATE INDEX IF NOT EXISTS idx_1115_nat_oper
    ON reg_1115 (nat_oper);

-- Tabelas de lookup estáticas (definidas pelo leiaute DIMP V10 / RCAD V06)
CREATE TABLE IF NOT EXISTS lkp_nat_oper (
    codigo    TEXT PRIMARY KEY,
    descricao TEXT NOT NULL,
    rcad_campo TEXT
);
CREATE TABLE IF NOT EXISTS lkp_ind_split (
    codigo    TEXT PRIMARY KEY,
    descricao TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lkp_ind_nat_jur (
    codigo    TEXT PRIMARY KEY,
    descricao TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lkp_ind_tp_pix (
    codigo    TEXT PRIMARY KEY,
    descricao TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lkp_tipo_tecnologia (
    codigo    TEXT PRIMARY KEY,
    descricao TEXT NOT NULL
);
"""

_SEED = """
INSERT OR IGNORE INTO lkp_nat_oper (codigo, descricao, rcad_campo) VALUES
    ('1',  'Cartão de Crédito',                                             'VT_NAT1'),
    ('2',  'Cartão de Débito',                                              'VT_NAT2'),
    ('3',  'Boleto de transações próprias',                                 'VT_NAT3'),
    ('4',  'Transferência de Recursos',                                     'VT_NAT4'),
    ('5',  'Pagamento em dinheiro ou outra estrutura',                      NULL),
    ('6',  'PIX',                                                           'VT_NAT6'),
    ('7',  'Voucher e cartão pré-pago',                                     NULL),
    ('8',  'Saque/troco em estabelecimento ou PIX Saque/Troco',            NULL),
    ('11', 'Recepção de boletos/guias de terceiros e recargas de celular',  NULL),
    ('12', 'PIX Garantido',                                                 'VT_PIX_GAR');

INSERT OR IGNORE INTO lkp_ind_split (codigo, descricao) VALUES
    ('0', 'Não splitado'),
    ('1', 'Splitado');

INSERT OR IGNORE INTO lkp_ind_nat_jur (codigo, descricao) VALUES
    ('0', 'CPF (Pessoa Física)'),
    ('1', 'CNPJ (Pessoa Jurídica)');

INSERT OR IGNORE INTO lkp_ind_tp_pix (codigo, descricao) VALUES
    ('0', 'Dinâmico'),
    ('1', 'Não Dinâmico');

INSERT OR IGNORE INTO lkp_tipo_tecnologia (codigo, descricao) VALUES
    ('1', 'TEF-POS Integrados'),
    ('2', 'Mobile'),
    ('3', 'POS'),
    ('4', 'E-commerce'),
    ('6', 'URA / MOTO / Backoffice / Atendimento'),
    ('7', 'Pagamento em Dinheiro / Outra Estrutura'),
    ('8', 'Conta Individual'),
    ('9', 'Conta Conjunta');
"""


def criar_banco(db_path: Path) -> None:
    """Cria o banco, aplica o schema e semeia os lookups (idempotente)."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_DDL)
        conn.executescript(_SEED)
        # Migrações incrementais — ADD COLUMN falha silenciosamente se já existir
        colunas_1110 = {r[1] for r in conn.execute("PRAGMA table_info(reg_1110)")}
        if "cnpj_liq" not in colunas_1110:
            conn.execute("ALTER TABLE reg_1110 ADD COLUMN cnpj_liq TEXT")
        # Seed de novas tabelas lookup em bancos antigos
        conn.executescript(_SEED)


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
        ErroRetificacao — se alguma regra V10 for violada (aborta sem gravar nada);
                          inclui retificação sem declaração normal prévia no banco
        ValueError      — se o arquivo não contiver registro 0000
    """
    criar_banco(db_path)

    # Coleta dados do parsing (ErroRetificacao propaga se violada)
    cabecalho_0000: Registro0000 | None = None
    cabecalho_00000: Registro00000 | None = None
    rows_0100: list[Registro0100] = []
    rows_0200: list[Registro0200] = []
    rows_1100: list[Registro1100] = []
    rows_1110: list[Registro1110] = []
    rows_1115: list[Registro1115] = []

    for ev in parse_dimp(caminho_dimp):
        if ev.reg == "00000":
            cabecalho_00000 = ev.registro  # type: ignore[assignment]
        elif ev.reg == "0000":
            cabecalho_0000 = ev.registro   # type: ignore[assignment]
        elif ev.reg == "0100":
            rows_0100.append(ev.registro)  # type: ignore[arg-type]
        elif ev.reg == "0200":
            rows_0200.append(ev.registro)  # type: ignore[arg-type]
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
    dt_ini_lote = cabecalho_0000.dt_ini   # período da declaração (AAAAMMDD)
    dt_fin_lote = cabecalho_0000.dt_fin   # período da declaração (AAAAMMDD)
    dt_tx = cabecalho_00000.dt_tx if cabecalho_00000 else ""
    hora_tx = cabecalho_00000.hora_tx if cabecalho_00000 else ""
    chave_lote = f"{cnpj}|{dt_tx}|{hora_tx}"

    # Monta chave_tx para prefixar as chaves dos filhos
    chave_tx = chave_lote

    deletados = 0

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

        # Valida existência de declaração normal antes de qualquer escrita
        # Período identificado por dt_ini + dt_fin, não por competencia,
        # para cobrir extemporâneos onde competencia ≠ mês dos dados.
        if finalidade == "2":
            existe_normal = conn.execute(
                "SELECT 1 FROM lote "
                "WHERE cnpj_ip = ? AND dt_ini = ? AND dt_fin = ? AND finalidade = '1'",
                (cnpj, dt_ini_lote, dt_fin_lote),
            ).fetchone()

            if not existe_normal:
                raise ErroRetificacao(
                    f"Erro V10: Nao existe declaracao normal (finalidade=1) "
                    f"para CNPJ {cnpj} periodo {dt_ini_lote} a {dt_fin_lote}. "
                    f"Processe o arquivo original antes da retificadora."
                )

        # --- Operação atômica ------------------------------------------------
        with conn:
            # Registra o lote
            conn.execute(
                "INSERT OR REPLACE INTO lote "
                "(chave_lote, cnpj_ip, competencia, finalidade, dt_tx, hora_tx, dt_ini, dt_fin) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chave_lote, cnpj, competencia, finalidade, dt_tx, hora_tx, dt_ini_lote, dt_fin_lote),
            )

            if finalidade == "2":
                # DELETE cirúrgico: remove apenas IND_EXTEMP='0' do período exato (dt_ini+dt_fin)
                # Preserva IND_EXTEMP='1' (extemporâneos de envios anteriores)
                cur = conn.execute(
                    "DELETE FROM reg_1100 "
                    "WHERE cnpj_ip = ? AND dt_ini = ? AND dt_fin = ? AND ind_extemp = '0'",
                    (cnpj, dt_ini_lote, dt_fin_lote),
                )
                deletados = cur.rowcount

            # INSERT 0100
            conn.executemany(
                "INSERT OR REPLACE INTO reg_0100 "
                "(chave_0100, chave_lote, cnpj_ip, cod_cliente, cnpj, cpf, nome_razao_social, uf) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"{chave_lote}|{r.cod_cliente}",
                        chave_lote, cnpj,
                        r.cod_cliente, r.cnpj, r.cpf,
                        r.nome_razao_social, r.uf,
                    )
                    for r in rows_0100
                ],
            )

            # INSERT 0200
            conn.executemany(
                "INSERT OR REPLACE INTO reg_0200 "
                "(chave_0200, chave_lote, cnpj_ip, cod_mcapt, cod_ip, tipo_tecnologia, marca) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"{chave_lote}|{r.cod_mcapt}",
                        chave_lote, cnpj,
                        r.cod_mcapt, r.cod_ip,
                        r.tipo_tecnologia, r.marca,
                    )
                    for r in rows_0200
                ],
            )

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
                " dt_operacao, valor_total, qtd_total, cnpj_liq) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"{chave_tx}|{_chave_1110(r)}",
                        f"{chave_tx}|{_chave_1100(r.pai_1100)}",
                        chave_lote,
                        r.cod_mcapt, r.dt_operacao,
                        str(r.valor_total_diario), r.qtd_total,
                        r.cnpj_liq,
                    )
                    for r in rows_1110
                ],
            )

            # INSERT 1115
            conn.executemany(
                "INSERT INTO reg_1115 "
                "(chave_pai_1110, chave_lote, nsu, cod_aut, id_transac, "
                " ind_split, bandeira, hora, valor, nat_oper, geo, ind_nat_jur, ind_tp_pix) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"{chave_tx}|{_chave_1110(r.pai_1110)}",
                        chave_lote,
                        r.nsu, r.cod_aut, r.id_transac,
                        r.ind_split, r.bandeira, r.hora,
                        str(r.valor_transacao), r.nat_oper,
                        r.geo, r.ind_nat_jur, r.ind_tp_pix,
                    )
                    for r in rows_1115
                ],
            )

    return {
        "finalidade": finalidade,
        "cnpj_ip": cnpj,
        "competencia": competencia,
        "chave_lote": chave_lote,
        "inseridos_0100": len(rows_0100),
        "inseridos_0200": len(rows_0200),
        "inseridos_1100": len(rows_1100),
        "inseridos_1110": len(rows_1110),
        "inseridos_1115": len(rows_1115),
        "deletados_1100": deletados,
    }
