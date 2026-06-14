# AI_DIMP — Documentação do Projeto

## Objetivo

Parser e visualizador de arquivos DIMP (Declaração de Informações sobre Movimentações Patrimoniais) entregues por instituições de pagamento à SEFAZ-PB. Complementa a aplicação QlikSense existente, oferecendo inspeção rápida e validação dos arquivos antes da carga.

## Estrutura de Arquivos

```
AI_DIMP/
├── app.py                  # Interface web (Streamlit)
├── processar_dimp.py       # Parser streaming dos arquivos DIMP
├── iniciar.bat             # Atalho para iniciar o app (duplo clique)
├── PROJECT.md              # Este arquivo — documentação do projeto
├── UPDATES.md              # Histórico de atualizações
├── originais/              # ZIPs recebidos das instituições de pagamento
├── extraidos/              # TXTs extraídos para análise (raiz = arquivos de referência rápida)
├── CONFAZ/                 # Documentação oficial do leiaute DIMP
└── docs/dimp_metadata/     # Dicionário de campos por registro
```

## Como Rodar

Dar duplo clique em `iniciar.bat` ou executar no terminal:

```powershell
cd "C:\Users\alexandre.rodrigues\Documents\AI_DIMP"
streamlit run app.py
```

Acessa em: `http://localhost:8501`

## Fluxo de Extração de ZIP

1. Colocar o ZIP recebido da IP em `originais/`
2. No app, painel **Extração de ZIP** → selecionar o ZIP → clicar **Extrair**
3. O app automaticamente:
   - Extrai para `extraidos/<nome_zip>/`
   - Prepende o conteúdo do `.elp` (cabeçalho de protocolo) ao `.txt` principal
   - Insere a linha `|00000|dt_tx|hora_tx|` antes do primeiro `|0000|`
   - Copia o `*-001.txt` para a raiz de `extraidos/` (ex: `W0119310-001.txt`)
4. O arquivo copiado aparece imediatamente no seletor **Fonte de dados**

## Formato do Arquivo DIMP

Texto pipe-delimited (`|`), encoding **ISO-8859-1**. Cada linha começa e termina com `|`.

### Registros suportados

| Registro | Descrição | Chave própria | FKs |
|---|---|---|---|
| `00000` | Transmissão — data e hora do protocolo ELP | `cnpj\|dt_tx\|hora_tx` | — |
| `0000` | Cabeçalho — IP declarante, período | `cnpj\|dt_tx\|hora_tx` | `chave_pai_00000` |
| `0100` | Cadastro de clientes (CPF / CNPJ) | — | `chave_pai_0000` |
| `0200` | Meios de captura (maquininhas) | — | `chave_pai_0000` |
| `1100` | Resumo mensal por cliente | `cnpj\|dt_tx\|hora_tx\|cod_cliente\|dt_ini\|dt_fin` | `chave_pai_0000` |
| `1110` | Resumo diário | `cnpj\|dt_tx\|hora_tx\|cod_cliente\|dt_ini\|dt_fin\|cod_mcapt\|dt_op` | `chave_pai_1100`, `chave_pai_0000` |
| `1115` | Transações individuais (NSU, valor, natureza) | — | `chave_pai_1110`, `chave_pai_1100`, `chave_pai_0000` |

### Hierarquia

```
00000 (1 por arquivo — data/hora de transmissão)
└── 0000 (1 por arquivo — cabeçalho da IP)
    ├── 0100* (n clientes)
    ├── 0200* (n meios de captura)
    └── 1100* (n resumos mensais)
        └── 1110* (n resumos diários)
            └── 1115* (n transações)
```

### Registro 00000 — origem do dt_tx

O campo `dt_tx` (data de transmissão) e `hora_tx` são extraídos em cascata:
1. String de protocolo `P<num>(AAAAMMDD)(HHMMSS)W` na primeira linha do arquivo (`.elp` prepended)
2. Data formatada `YYYY/MM/DD HH:MM:SS` no cabeçalho
3. Padrão `DD-MM-YYYY_HHMMSS` no nome do caminho do arquivo

### Chave composta — unicidade global

Todas as chaves são prefixadas com `cnpj|dt_tx|hora_tx` (a chave do `00000`), garantindo que
registros de instituições diferentes nunca colidam, mesmo que tenham `cod_cliente` idêntico.
O CNPJ é armazenado como string pura (14 dígitos, sem máscara), conforme o layout oficial DIMP V10.

## Banco de Dados SQLite (`persistencia.py`)

Gerado ao chamar `processar_lote(db_path, caminho_dimp)`.

### Tabelas

| Tabela | PK | Descrição |
|---|---|---|
| `lote` | `chave_lote` | Um lote por arquivo — `cnpj\|dt_tx\|hora_tx` |
| `reg_0100` | `chave_0100` | Clientes cadastrados — ligado a `reg_1100` via `cnpj_ip + cod_cliente` |
| `reg_0200` | `chave_0200` | Meios de captura — ligado a `reg_1110` via `cnpj_ip + cod_mcapt` |
| `reg_1100` | `chave_1100` | Resumos mensais por cliente |
| `reg_1110` | `chave_1110` | Operações diárias (`ON DELETE CASCADE` de `reg_1100`) |
| `reg_1115` | `id` auto | Transações individuais (`ON DELETE CASCADE` de `reg_1110`) |
| `lkp_nat_oper` | `codigo` | Naturezas de operação com campo RCAD (VT_NAT1, VT_NAT6…) |
| `lkp_ind_split` | `codigo` | 0=não splitado, 1=splitado |
| `lkp_ind_nat_jur` | `codigo` | 0=CPF(PF), 1=CNPJ(PJ) |
| `lkp_ind_tp_pix` | `codigo` | 0=Dinâmico, 1=Não Dinâmico |
| `lkp_tipo_tecnologia` | `codigo` | 1=TEF-POS Integrados, 2=Mobile, 3=POS, 4=E-commerce, 6=URA/MOTO, 7=Dinheiro/Outra, 8=Conta Individual, 9=Conta Conjunta |

### Ligações cadastrais

```sql
-- Cliente → resumo mensal
SELECT r0.nome_razao_social, r1.valor
FROM reg_0100 r0
JOIN reg_1100 r1 ON r0.cnpj_ip = r1.cnpj_ip AND r0.cod_cliente = r1.cod_cliente;

-- Meio de captura → operações diárias
SELECT r2.tipo_tecnologia, r11.dt_operacao, r11.valor_total
FROM reg_0200 r2
JOIN lote l ON l.cnpj_ip = r2.cnpj_ip
JOIN reg_1110 r11 ON r11.chave_lote = l.chave_lote AND r11.cod_mcapt = r2.cod_mcapt;
```

## Módulo `processar_dimp.py`

Parser streaming via generator — não carrega o arquivo inteiro em memória.

```python
from processar_dimp import parse_dimp
from pathlib import Path

for evento in parse_dimp(Path("arquivo.txt")):
    print(evento.reg, evento.registro)
```

Valida automaticamente a soma de `1115` dentro de cada `1110`, e a soma de `1110` dentro de cada `1100`, emitindo `WARNING` em caso de divergência.

Linhas malformadas são ignoradas com `WARNING` em vez de abortar o arquivo.

## Seções do app Streamlit

| Seção | Descrição |
|---|---|
| Extração de ZIP | Painel lateral — extrai ZIP, prepende ELP, copia para raiz de `extraidos/` |
| Tabelas por registro | Abas 00000 / 0000 / 0100 / 0200 / 1100 / 1110 / 1115 com busca e exportação CSV |
| Comparação de Valores | 1100 vs soma 1110 · 1110 vs soma 1115 — divergências com status OK/DIVERGENTE |
| Validação Cadastral | Órfãos 0100↔1100 e 0200↔1110 |
| Consulta CPF/CNPJ | KPIs + tabelas 1100/1110/1115 centralizadas (HTML), com separador de milhar nas quantidades |
| Auditoria de Quantidades | Compara QTD 1100 vs soma 1110 vs contagem 1115 |

## Arquivos de análise disponíveis

| Arquivo | IP | Competência |
|---|---|---|
| `extraidos/W0119311-001.txt` | BRASIL CARD (CNPJ 03130170000189) | abril/2026 |
| `extraidos/W0119310-001.txt` | ALELO SA (CNPJ 04740876000125) | abril/2026 |

## Contexto QlikSense

Aplicação principal em `http://10.10.254.152` (versão 4.14f+). Fluxo ETL:
1. **Extração** — leitura dos arquivos `.txt` pipe-delimited
2. **Transformação** — chaves de ligação entre registros (ver `CHAVES DE LIGAÇÃO.txt`)
3. **Load** — carga nos QVDs e dashboards

## Dependências Python

```
streamlit>=1.37
```

Parser usa apenas biblioteca padrão (`dataclasses`, `decimal`, `logging`, `pathlib`).
