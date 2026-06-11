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

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `DIMP_ARQUIVO_EXEMPLO` | arquivo PicPay incluído no repo | Arquivo carregado automaticamente se nenhum for enviado via upload |

## Formato do Arquivo DIMP

Texto pipe-delimited (`|`), encoding **ISO-8859-1**. Cada linha começa e termina com `|`.

### Registros suportados

| Registro | Descrição |
|---|---|
| `0000` | Cabeçalho — identifica a instituição de pagamento e o período |
| `0100` | Cadastro de clientes (CPF / CNPJ) |
| `0200` | Meios de captura (maquininhas) |
| `1100` | Resumo mensal por cliente |
| `1110` | Resumo diário dentro do `1100` |
| `1115` | Transações individuais (NSU, valor, natureza) |

### Hierarquia

```
0000 (1 por arquivo)
└── 0100* (n clientes)
└── 0200* (n meios de captura)
└── 1100* (n resumos mensais)
    └── 1110* (n resumos diários)
        └── 1115* (n transações)
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
