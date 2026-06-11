# UPDATES — Histórico de Atualizações

---

## 2026-06-11 — Tabulação completa dos dados

### `processar_dimp.py` — campos expandidos
- **0000**: adicionados `situacao` (pos 8) e `competencia` (pos 9)
- **0100**: adicionados `logradouro`, `cep`, `cod_municipio`, `uf`, `nome_contato`, `telefone`, `email`, `dt_inicio`, `flag` — passa de 4 para 13 campos
- **0200**: adicionados `cod_ip` (pos 2) e `flag` (pos 4)
- **1115**: adicionados `cod_aut` (pos 2), `flag` (pos 4), `hora` (pos 6), `qtd` (pos 8) — passa de 4 para 8 campos

### `app.py` — interface tabulada
- Layout reorganizado em **abas por tipo de registro** (0000 / 0100 / 0200 / 1100 / 1110 / 1115)
- Cada aba tem busca própria e botão **"Exportar como CSV"** (encoding UTF-8 BOM para Excel)
- `carregar_eventos` agora retorna `dict[reg → lista]` em vez de lista plana — amostra separada por registro

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
