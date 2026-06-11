# UPDATES — Histórico de Atualizações

---

## 2026-06-11 — Otimizações de Escalabilidade e Resiliência

### `processar_dimp.py`
- **Resiliência por linha**: cada linha do arquivo agora é processada dentro de `try/except (ValueError, IndexError)`. Linhas malformadas emitem `WARNING` e são ignoradas em vez de abortar o arquivo inteiro.
- **1110/1115 sem pai**: substituído `raise ValueError` por `LOG.warning + continue` quando um registro `1110` ou `1115` aparece fora de contexto hierárquico.

### `app.py`
- **Serialização sem recursão**: `asdict()` substituído por iteração via `dataclasses.fields()` filtrando campos que são dataclasses (ex: `pai_1110`, `pai_1100`). Evita expansão recursiva de 3 níveis por linha do registro `1115`.
- **Logging estruturado**: adicionado `logging.basicConfig` com formato `timestamp + nível + nome + mensagem`.
- **Try/except no processamento**: bloco de carregamento do arquivo envolto em `try/except Exception`, exibindo erro na UI via `st.error` em vez de travar o app.
- **Variável de ambiente**: caminho do arquivo exemplo lê `DIMP_ARQUIVO_EXEMPLO` via `os.environ.get`, mantendo o padrão atual como fallback.

### Novos arquivos
- `iniciar.bat` — duplo clique inicia o Streamlit sem precisar abrir terminal
- `PROJECT.md` — documentação completa do projeto para onboarding rápido
- `UPDATES.md` — este arquivo

---

## Versões anteriores

> Histórico da aplicação QlikSense (pré-Python) documentado em `apoio_servidor 1.0.txt`.
