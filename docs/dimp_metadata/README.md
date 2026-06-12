# Contexto tecnico DIMP para IA

Referencia rapida dos registros DIMP V10 para agentes de IA e consultas tecnicas.

## Hierarquia completa

```
00000  Transmissao (data/hora do protocolo ELP)
└── 0000  Cabecalho — IP declarante, periodo, finalidade
    ├── 0100*  Cadastro de clientes (COD_CLIENTE)
    ├── 0200*  Cadastro de meios de captura (COD_MCAPT)
    └── 1100*  Resumo mensal por cliente
          └── 1110*  Operacoes diarias por meio de captura
                └── 1115*  Transacao individual (NSU/valor/natureza)
```

## Ligacoes entre blocos (integridade referencial)

| Bloco 0 (Cadastro) | Campo | Bloco 1 (Operacoes) | Campo | Relacao |
|---|---|---|---|---|
| `0100` | COD_CLIENTE | `1100` | COD_CLIENTE | 1:N — um cliente, varios meses |
| `0200` | COD_MCAPT | `1110` | COD_MCAPT | 1:N — um terminal, varios dias |

Violacao (registro em 1100/1110 sem cadastro em 0100/0200) = **residuo proibido V10**.
O parser emite WARNING; o app exibe na secao "Validacao de Cadastro vs Operacoes".

## Schema SQLite (persistencia.py)

| Tabela | PK | Descricao |
|---|---|---|
| `lote` | chave_lote | Um lote por arquivo (cnpj\|dt_tx\|hora_tx) |
| `reg_0100` | chave_0100 | Clientes cadastrados — JOIN com reg_1100 |
| `reg_0200` | chave_0200 | Meios de captura — JOIN com reg_1110 |
| `reg_1100` | chave_1100 | Resumos mensais |
| `reg_1110` | chave_1110 | Operacoes diarias (ON DELETE CASCADE de reg_1100) |
| `reg_1115` | id (auto) | Transacoes individuais (ON DELETE CASCADE de reg_1110) |
| `lkp_nat_oper` | codigo | Lookup: naturezas de operacao (1=credito, 6=PIX, 12=PIX Garantido) |
| `lkp_ind_split` | codigo | Lookup: 0=nao splitado, 1=splitado |
| `lkp_ind_nat_jur` | codigo | Lookup: 0=CPF(PF), 1=CNPJ(PJ) |
| `lkp_ind_tp_pix` | codigo | Lookup: 0=Dinamico, 1=Nao Dinamico |

## JOINs uteis

```sql
-- Cliente -> valor mensal
SELECT r0.nome_razao_social, r1.dt_ini, r1.dt_fin, r1.valor
FROM reg_0100 r0
JOIN reg_1100 r1 ON r0.cnpj_ip = r1.cnpj_ip AND r0.cod_cliente = r1.cod_cliente;

-- Meio de captura -> operacoes diarias
SELECT r2.tipo_tecnologia, r11.dt_operacao, r11.valor_total
FROM reg_0200 r2
JOIN lote l ON l.cnpj_ip = r2.cnpj_ip
JOIN reg_1110 r11 ON r11.chave_lote = l.chave_lote AND r11.cod_mcapt = r2.cod_mcapt;

-- Transacoes por natureza de operacao
SELECT lk.descricao, COUNT(*) as qtd, SUM(CAST(r.valor AS REAL)) as total
FROM reg_1115 r
JOIN lkp_nat_oper lk ON lk.codigo = r.nat_oper
GROUP BY r.nat_oper;
```

## Regras de totalicao

```
SUM(1115.valor)               == 1110.valor_total
SUM(1110.valor_total)         == 1100.valor
```

Divergencias sao detectadas pelo app na secao "Comparacao de Valores".

## Regras de retificacao (finalidade=2)

- Registros `1200` e `1600` sao proibidos.
- `IND_EXTEMP=1` no `1100` e proibido.
- Chave de periodo: `cnpj_ip + dt_ini + dt_fin` (nao `competencia`).
- DELETE cirurgico: remove apenas `ind_extemp='0'` do periodo, preservando
  extemporaneos de envios anteriores.
- Obrigatorio: declaracao normal (finalidade=1) deve existir antes da retificadora.

## Documentos por registro

| Registro | Documento | Papel |
|---|---|---|
| `0100` | [0100.md](0100.md) | Cadastro de clientes |
| `0200` | [0200.md](0200.md) | Cadastro de meios de captura |
| `1100` | [1100.md](1100.md) | Resumo mensal por cliente |
| `1110` | [1110.md](1110.md) | Operacoes diarias |
| `1115` | [1115.md](1115.md) | Detalhes de transacao (campos corrigidos V10) |
