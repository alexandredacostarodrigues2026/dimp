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

| Registro | Descrição | Chave de ligação |
|---|---|---|
| `00000` | Transmissão — data e hora extraídas do protocolo ELP | `chave_00000 = dt_tx\|hora_tx` |
| `0000` | Cabeçalho — IP declarante, período | FK: `chave_pai_00000` |
| `0100` | Cadastro de clientes (CPF / CNPJ) | — |
| `0200` | Meios de captura (maquininhas) | — |
| `1100` | Resumo mensal por cliente | `chave_1100 = cod_cliente\|dt_ini\|dt_fin` |
| `1110` | Resumo diário dentro do `1100` | FK: `chave_pai_1100`; `chave_1110 = chave_1100\|cod_mcapt\|dt_operacao` |
| `1115` | Transações individuais (NSU, valor, natureza) | FK: `chave_pai_1110`, `chave_pai_1100` |

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
