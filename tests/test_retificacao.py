"""
Testes V10: regras de negócio para Finalidade 1 (Normal) e 2 (Retificação).
Execute com: python -m pytest tests/test_retificacao.py -v
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from processar_dimp import ErroRetificacao, parse_dimp
from persistencia import criar_banco, processar_lote

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CNPJ = "12345678000195"
_CABECALHO_00000 = "|00000|20260513|144444|\n"
_CABECALHO_0000 = "|0000|09|{finalidade}|PB|{cnpj}|EMPRESA TESTE|{dt_ini}|{dt_fin}|1|{competencia}|\n"
_REG_1100 = "|1100|00000000000000|999|0|{ind_extemp}|{dt_ini}|{dt_fin}|100,00|1|\n"
_REG_1110 = "|1110|TERM001|20260401|100,00|1|{cnpj}|\n"
_REG_1115 = "|1115|NSU001||ID001|0|01|000000|100,00|1|\n"
_REG_1200 = "|1200|campo1|campo2|\n"
_REG_1600 = "|1600|campo1|campo2|\n"

_DT_INI = "20260401"
_DT_FIN = "20260430"
_COMPETENCIA = "202605"


def _dimp(
    finalidade: str,
    ind_extemp: str = "0",
    extra: str = "",
    dt_ini: str = _DT_INI,
    dt_fin: str = _DT_FIN,
    competencia: str = _COMPETENCIA,
) -> str:
    return (
        _CABECALHO_00000
        + _CABECALHO_0000.format(
            finalidade=finalidade, cnpj=_CNPJ,
            dt_ini=dt_ini, dt_fin=dt_fin, competencia=competencia,
        )
        + _REG_1100.format(ind_extemp=ind_extemp, dt_ini=dt_ini, dt_fin=dt_fin)
        + _REG_1110.format(cnpj=_CNPJ)
        + _REG_1115
        + extra
    )


def _arquivo_temp(conteudo: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", encoding="iso-8859-1", suffix=".txt", delete=False
    )
    f.write(conteudo)
    f.flush()
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# Testes de validação do parser (ErroRetificacao)
# ---------------------------------------------------------------------------

class TestValidacaoParser:

    def test_finalidade1_ind_extemp1_permitido(self):
        """Finalidade 1 aceita IND_EXTEMP=1 sem erro."""
        arq = _arquivo_temp(_dimp("1", ind_extemp="1"))
        eventos = list(parse_dimp(arq))
        regs = [ev.reg for ev in eventos]
        assert "1100" in regs

    def test_finalidade1_sem_restricao_1200(self):
        """Finalidade 1 não bloqueia registro 1200."""
        arq = _arquivo_temp(_dimp("1") + _REG_1200)
        # 1200 é desconhecido pelo parser mas não lança erro em finalidade 1
        list(parse_dimp(arq))  # não deve lançar

    def test_finalidade2_ind_extemp1_bloqueado(self):
        """Finalidade 2 com IND_EXTEMP=1 no 1100 deve lançar ErroRetificacao."""
        arq = _arquivo_temp(_dimp("2", ind_extemp="1"))
        with pytest.raises(ErroRetificacao, match="IND_EXTEMP=1"):
            list(parse_dimp(arq))

    def test_finalidade2_registro_1200_bloqueado(self):
        """Finalidade 2 com registro 1200 deve lançar ErroRetificacao."""
        arq = _arquivo_temp(_dimp("2") + _REG_1200)
        with pytest.raises(ErroRetificacao, match="1200"):
            list(parse_dimp(arq))

    def test_finalidade2_registro_1600_bloqueado(self):
        """Finalidade 2 com registro 1600 deve lançar ErroRetificacao."""
        arq = _arquivo_temp(_dimp("2") + _REG_1600)
        with pytest.raises(ErroRetificacao, match="1600"):
            list(parse_dimp(arq))

    def test_finalidade2_ind_extemp0_permitido(self):
        """Finalidade 2 com todos IND_EXTEMP=0 deve processar sem erro."""
        arq = _arquivo_temp(_dimp("2", ind_extemp="0"))
        eventos = list(parse_dimp(arq))
        regs = [ev.reg for ev in eventos]
        assert "1100" in regs


# ---------------------------------------------------------------------------
# Testes de persistência (processar_lote)
# ---------------------------------------------------------------------------

class TestPersistencia:

    def _novo_banco(self) -> Path:
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        return Path(f.name)

    def test_finalidade1_insere_normalmente(self):
        """Finalidade 1 realiza INSERT dos registros."""
        db = self._novo_banco()
        arq = _arquivo_temp(_dimp("1", ind_extemp="0"))
        resultado = processar_lote(db, arq)

        assert resultado["finalidade"] == "1"
        assert resultado["inseridos_1100"] == 1
        assert resultado["inseridos_1110"] == 1
        assert resultado["inseridos_1115"] == 1
        assert resultado["deletados_1100"] == 0

        with sqlite3.connect(db) as conn:
            qtd = conn.execute("SELECT COUNT(*) FROM reg_1100").fetchone()[0]
        assert qtd == 1

    def test_finalidade1_aceita_ind_extemp1(self):
        """Finalidade 1 insere registros com IND_EXTEMP=1 normalmente."""
        db = self._novo_banco()
        arq = _arquivo_temp(_dimp("1", ind_extemp="1"))
        resultado = processar_lote(db, arq)
        assert resultado["inseridos_1100"] == 1

        with sqlite3.connect(db) as conn:
            extemp = conn.execute(
                "SELECT ind_extemp FROM reg_1100"
            ).fetchone()[0]
        assert extemp == "1"

    def test_finalidade2_delete_apenas_extemp0(self):
        """Finalidade 2 apaga IND_EXTEMP='0' e preserva IND_EXTEMP='1'."""
        db = self._novo_banco()
        criar_banco(db)

        # Pré-carrega: 1 registro extemp=0 e 1 extemp=1 simulados diretamente
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO lote "
                "(chave_lote, cnpj_ip, competencia, finalidade, dt_tx, hora_tx, dt_ini, dt_fin) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("LOTE_ANTIGO", _CNPJ, _COMPETENCIA, "1", "20260401", "080000", _DT_INI, _DT_FIN),
            )
            conn.executemany(
                "INSERT INTO reg_1100 "
                "(chave_1100, chave_lote, cnpj_ip, competencia, cod_cliente, "
                " ind_extemp, dt_ini, dt_fin, valor, qtd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    # IND_EXTEMP=0: período do lote → deve ser apagado pela retificação
                    ("CHAVE_NORMAL", "LOTE_ANTIGO", _CNPJ, _COMPETENCIA,
                     "CLI_A", "0", _DT_INI, _DT_FIN, "500.00", 1),
                    # IND_EXTEMP=1 em período diferente → deve ser preservado
                    ("CHAVE_EXTEMP", "LOTE_ANTIGO", _CNPJ, _COMPETENCIA,
                     "CLI_B", "1", "20260301", "20260331", "200.00", 1),
                ],
            )

        # Retificação: deve apagar CLI_A (extemp=0) e manter CLI_B (extemp=1)
        arq = _arquivo_temp(_dimp("2", ind_extemp="0"))
        resultado = processar_lote(db, arq)

        assert resultado["finalidade"] == "2"
        assert resultado["deletados_1100"] == 1        # só CLI_A foi deletado
        assert resultado["inseridos_1100"] == 1        # novo registro inserido

        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT cod_cliente, ind_extemp FROM reg_1100 WHERE cnpj_ip = ?",
                (_CNPJ,),
            ).fetchall()

        cod_clientes = {r[0] for r in rows}
        assert "CLI_B" in cod_clientes        # extemporâneo preservado
        assert "CLI_A" not in cod_clientes    # normal do período anterior apagado

    def test_finalidade2_sem_normal_previa_bloqueado(self):
        """Retificação sem declaração normal prévia no banco deve lançar ErroRetificacao."""
        db = self._novo_banco()
        arq = _arquivo_temp(_dimp("2", ind_extemp="0"))

        with pytest.raises(ErroRetificacao, match="finalidade=1"):
            processar_lote(db, arq)

        with sqlite3.connect(db) as conn:
            qtd = conn.execute("SELECT COUNT(*) FROM reg_1100").fetchone()[0]
        assert qtd == 0  # nada foi gravado

    def test_finalidade2_com_normal_previa_aceito(self):
        """Retificação com declaração normal prévia no banco deve processar normalmente."""
        db = self._novo_banco()

        # Primeiro: processa o arquivo normal
        arq_normal = _arquivo_temp(_dimp("1", ind_extemp="0"))
        resultado_normal = processar_lote(db, arq_normal)
        assert resultado_normal["finalidade"] == "1"

        # Depois: processa a retificadora para o mesmo CNPJ + competência
        arq_retif = _arquivo_temp(_dimp("2", ind_extemp="0"))
        resultado_retif = processar_lote(db, arq_retif)
        assert resultado_retif["finalidade"] == "2"
        assert resultado_retif["deletados_1100"] >= 1

    def test_finalidade2_erro_aborts_sem_gravar(self):
        """ErroRetificacao em finalidade 2 não persiste nenhum dado."""
        db = self._novo_banco()
        arq = _arquivo_temp(_dimp("2", ind_extemp="1"))  # viola a regra

        with pytest.raises(ErroRetificacao):
            processar_lote(db, arq)

        with sqlite3.connect(db) as conn:
            qtd = conn.execute("SELECT COUNT(*) FROM reg_1100").fetchone()[0]
        assert qtd == 0  # nada foi gravado

    def test_finalidade2_periodo_diferente_bloqueado(self):
        """Retificação com dt_ini/dt_fin diferente do normal deve lançar ErroRetificacao.

        Cobre o caso extemporâneo: a normal existe para abril, mas a retificação
        declara período de maio → não deve encontrar correspondência.
        """
        db = self._novo_banco()

        # Normal para abril/2026
        arq_normal = _arquivo_temp(_dimp("1", dt_ini="20260401", dt_fin="20260430"))
        processar_lote(db, arq_normal)

        # Retificação declara maio/2026 — período diferente, não existe normal para ele
        arq_retif = _arquivo_temp(
            _dimp("2", dt_ini="20260501", dt_fin="20260531", competencia="202606")
        )
        with pytest.raises(ErroRetificacao, match="finalidade=1"):
            processar_lote(db, arq_retif)

        with sqlite3.connect(db) as conn:
            qtd = conn.execute("SELECT COUNT(*) FROM reg_1100").fetchone()[0]
        assert qtd == 1  # só o normal de abril, nada da retif de maio
