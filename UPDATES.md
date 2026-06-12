# UPDATES — Histórico de Atualizações

---

## 2026-06-12 — Ligações cadastrais 0100↔1100 e 0200↔1110 com validação V10

### Problema resolvido
Os registros do Bloco 0 (cadastro) e Bloco 1 (operações) não estavam ligados
entre si, impossibilitando JOIN entre cliente/terminal e seus respectivos resumos.

### `processar_dimp.py`
- Parser emite `WARNING` quando `1100.COD_CLIENTE` não existe em `0100` (resíduo V10).
- Parser emite `WARNING` quando `1110.COD_MCAPT` não existe em `0200` (resíduo V10).

### `app.py`
- `Registro1100` serializado com `chave_pai_0100 = cnpj|dt_tx|hora_tx|cod_cliente`.
- `Registro1110` serializado com `chave_pai_0200 = cnpj|dt_tx|hora_tx|cod_mcapt`.
- Nova função `gerar_validacao()` — passagem completa detectando órfãos.
- Nova seção **"Validação de Cadastro vs Operações"** com métricas e detalhes dos órfãos.

### `persistencia.py`
- Novas tabelas `reg_0100` e `reg_0200` com índices `(cnpj_ip, cod_cliente/cod_mcapt)`.
- `processar_lote` coleta e insere `0100`/`0200` no mesmo bloco atômico.
- Retorno inclui `inseridos_0100` e `inseridos_0200`.

### Verificado com arquivo real (W0119353-001.txt — Banco CSF SA, abril/2026)
- 13 clientes (0100) → 13 resumos (1100): **0 órfãos**
- 4 meios de captura (0200) → 1.141 operações diárias (1110): **0 órfãos**
- 99.228 transações (1115) persistidas com integridade

---

## 2026-06-12 — Campos 1115 corrigidos + lookups de natureza de operação

### Campos Registro1115 (corrigidos contra o layout oficial DIMP V10 p.38)

| Campo anterior | Campo correto | Posição | Observação |
|---|---|---|---|
| `flag` | `ind_split` | 05 | Nome errado |
| `natureza_operacao` | `bandeira` | 06 | Estava mapeando BANDEIRA como NAT_OPER |
| `qtd` (int) | `nat_oper` (str) | 09 | Tipo e semântica errados |
| — | `geo` | 10 | Campo novo |
| — | `ind_nat_jur` | 11 | Campo novo |
| — | `ind_tp_pix` | 12 | Campo novo |

### Lookups criados em `persistencia.py`
- `lkp_nat_oper` — 10 naturezas com coluna `rcad_campo` (VT_NAT1, VT_NAT6, VT_PIX_GAR…)
- `lkp_ind_split`, `lkp_ind_nat_jur`, `lkp_ind_tp_pix` — semeados em `criar_banco`

### `app.py`
- Aba `1115` exibe colunas `nat_oper_desc`, `ind_split_desc`, `ind_nat_jur_desc`, `ind_tp_pix_desc`.
- Expander "Resumo por Natureza de Operação" com qtd e valor total agrupados.

---

## 2026-06-12 — Chave de período: competencia → dt_ini + dt_fin

### Problema resolvido
A retificação usava `competencia` (AAAAMM) para identificar o período a ser substituído.
Isso causava dois cenários de falha:
1. Duas declarações normais do mesmo CNPJ com mesma competência mas períodos distintos (ex: `01-15/mês` e `16-30/mês`) colidiam.
2. Registros extemporâneos: `competencia` do arquivo não coincide com o mês real dos dados (`dt_ini`/`dt_fin` do `1100`), então o DELETE eliminava registros errados.

### `persistencia.py`
- **Schema `lote`**: adicionadas colunas `dt_ini TEXT NOT NULL` e `dt_fin TEXT NOT NULL` (período declarado no `0000`).
- **Índice `idx_1100_retificacao`**: alterado de `(cnpj_ip, competencia, ind_extemp)` para `(cnpj_ip, dt_ini, dt_fin, ind_extemp)`.
- **Existência de normal**: query agora usa `WHERE cnpj_ip = ? AND dt_ini = ? AND dt_fin = ? AND finalidade = '1'`.
- **DELETE cirúrgico**: usa `WHERE cnpj_ip = ? AND dt_ini = ? AND dt_fin = ? AND ind_extemp = '0'`.
- Período `dt_ini`/`dt_fin` extraído de `cabecalho_0000` (campo do `Registro0000`).

### `tests/test_retificacao.py`
- Templates `_CABECALHO_0000` e `_REG_1100` parametrizados com `{dt_ini}`/`{dt_fin}`.
- Helper `_dimp()` aceita `dt_ini`, `dt_fin`, `competencia` com padrões; chamadas existentes inalteradas.
- `test_finalidade2_delete_apenas_extemp0`: pre-load do `lote` inclui `dt_ini`/`dt_fin`; CLI_B (extemp=1) preservado tanto por `ind_extemp` quanto por período diferente.
- **Novo**: `test_finalidade2_periodo_diferente_bloqueado` — retificação com período de maio bloqueada quando normal existe apenas para abril.
- Total: **13 testes, todos passando**.

---

## 2026-06-12 — Padronização de chaves compostas globalmente únicas

### Problema resolvido
`chave_0000 = cnpj_ip` e `chave_1100 = cod_cliente|dt_ini|dt_fin` não eram únicas em escala:
duas IPs distintas podiam ter o mesmo `cod_cliente` no mesmo período, gerando colisão.

### Modelo de chaves após refatoração

| Registro | Chave própria | Chave FK para pai |
|---|---|---|
| `00000` | `cnpj\|dt_tx\|hora_tx` | — |
| `0000` | `cnpj\|dt_tx\|hora_tx` | `chave_pai_00000` |
| `0100` / `0200` | — | `chave_pai_0000 = cnpj\|dt_tx\|hora_tx` |
| `1100` | `cnpj\|dt_tx\|hora_tx\|cod_cliente\|dt_ini\|dt_fin` | `chave_pai_0000` |
| `1110` | `cnpj\|dt_tx\|hora_tx\|cod_cliente\|dt_ini\|dt_fin\|cod_mcapt\|dt_operacao` | `chave_pai_1100`, `chave_pai_0000` |
| `1115` | — | `chave_pai_1110`, `chave_pai_1100`, `chave_pai_0000` |

### `app.py`
- `serializar_registro`: parâmetro `chave_ip` removido — agora recebe apenas `chave_tx` (`cnpj|dt_tx|hora_tx`).
- `chave_0000` e `chave_pai_00000` em `0000` usam `chave_tx` diretamente.
- `chave_1100` serializado como `f"{chave_tx}|{chave_1100(r)}"`.
- `chave_1110` serializado como `f"{chave_tx}|{chave_1110(r)}"`.
- Todos os `chave_pai_*` nos filhos seguem o mesmo padrão de prefixo.
- **Fix**: `chave_00000` incompleta — `dt_tx|hora_tx` agora lido diretamente de `evento.registro`, não do row (que estava vazio antes do cnpj ser conhecido).

### `processar_dimp.py`
- `chave_00000(r, cnpj_ip="")`: aceita cnpj opcional; fallback para `dt_tx|hora_tx` isolado.
- `chave_0000(r, chave_tx="")`: aceita chave_tx opcional; fallback para `cnpj_ip` isolado.

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
