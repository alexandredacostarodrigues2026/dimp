# UPDATES — Histórico de Atualizações

---

## 2026-06-11 — Cópia automática para raiz de extraidos e chaves de hierarquia completas

### `app.py`
- **Cópia automática ao extrair**: ao clicar "Extrair", o `*-001.txt` é copiado para a raiz de `extraidos/` (ex: `W0119310-001.txt`) sem intervenção manual.
- **`_listar_extraidos`**: passa a listar `.txt` diretamente na raiz de `extraidos/` (não mais nos subdiretórios). Fonte de dados do app aponta para `C:\Users\alexandre.rodrigues\Documents\AI_DIMP\extraidos`.
- **Registro `00000`** recebe campo `chave_00000 = dt_tx|hora_tx` na serialização.
- **Registro `0000`** recebe campo `chave_pai_00000` linkando ao `00000` pai.
- Imports organizados no topo (`re`, `shutil` saem dos imports inline para o cabeçalho do módulo).

### `processar_dimp.py`
- Nova função `chave_00000(r: Registro00000) -> str` — retorna `dt_tx|hora_tx`.

---

## 2026-06-11 — Registro 00000 (transmissão) e extração de protocolo ELP

### Contexto
Arquivos BRASIL-CARD chegam em ZIP com um arquivo `.elp` separado contendo a string de protocolo
(`P3854146120260511111331W`) que identifica a data e hora exata de transmissão.
O arquivo principal `.txt` começa diretamente em `|0000|` sem cabeçalho de protocolo na primeira linha.

### `processar_dimp.py`
- **Novo dataclass `Registro00000`**: registro pai do `0000`, com dois campos — `dt_tx` (AAAAMMDD) e `hora_tx` (HHMMSS).
- **Emissão do `00000`**:
  - Se o arquivo contém fisicamente a linha `|00000|dt|hora|`, lê de lá (prioridade).
  - Caso contrário, emite sinteticamente antes do primeiro `0000`, usando `_extrair_dt_transmissao`.
- **Guard contra duplicata**: `|0000|` na seção de totais (`|9900|`) é ignorado silenciosamente (`if estado.abertura is not None: continue`).
- **`_extrair_dt_transmissao`**: três fontes em cascata — (1) regex `P\d*?(20\d{6})(\d{6})W` na primeira linha, (2) `YYYY/MM/DD HH:MM:SS` no cabeçalho, (3) padrão `DD-MM-YYYY_HHMMSS` no caminho completo do arquivo.

### `app.py`
- **`_extrair_zip_para_pasta`**: ao extrair o ZIP, o conteúdo do `.elp` é prefixado ao `.txt` principal e a linha `|00000|dt_tx|hora_tx|` é inserida antes do `|0000|`.
- **`REGISTROS_ALVO`** inclui `"00000"` e a aba correspondente aparece na interface como "Transmissao".
- **`serializar_registro`**: `Registro00000` serializado normalmente (apenas `dt_tx` e `hora_tx`).

### Arquivo de análise
- `extraidos/W0119311-001.txt` — cópia do BRASIL-CARD com ELP prepended e linha `|00000|20260511|111331|` inserida, disponibilizada na raiz de `extraidos/` para inspeção rápida.

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
