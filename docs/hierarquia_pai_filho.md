# Padrão Hierárquico Pai-Filho em Arquivos Fiscais Pipe-Delimitados

## Contexto

Arquivos fiscais brasileiros (DIMP, EFD, ECD, ECF e outros do ecossistema SPED) compartilham o mesmo
formato estrutural: texto delimitado por pipe (`|`), encoding ISO-8859-1, onde cada linha representa
um registro de um tipo específico. A hierarquia entre os registros não é expressa por indentação ou
aninhamento físico — ela é **implícita pelo contexto de leitura sequencial**.

Este documento descreve o padrão de implementação adotado para representar, serializar e validar
essa hierarquia em Python, de forma reutilizável para qualquer leiaute fiscal com estrutura pai-filho.

---

## 1. Princípio Fundamental

Em um arquivo fiscal hierárquico, **um registro filho sempre pertence ao último registro pai do mesmo
nível que foi lido antes dele**. A hierarquia é definida pela ordem das linhas no arquivo, não por
campos de referência explícitos no layout oficial.

```
[Raiz]
  └── [Cabeçalho]           ← um por arquivo
        ├── [Entidade A]*   ← n registros
        ├── [Entidade B]*
        └── [Resumo]*       ← n grupos
              └── [Detalhe Diário]*   ← n por grupo
                    └── [Transação]*  ← n por detalhe
```

A leitura é feita linha a linha (streaming). Ao encontrar um registro de nível N, o parser
"ativa" esse registro como contexto para os registros de nível N+1 que vierem a seguir.

---

## 2. Chave Composta Global

O leiaute oficial define identificadores locais (ex: código do cliente, data de operação), mas esses
identificadores **não são únicos globalmente** quando dados de múltiplos declarantes são processados
em conjunto.

A solução é construir uma **chave composta** que propague o identificador do nível raiz para todos
os descendentes:

```
chave_raiz      = {identificador_declarante}|{data_envio}|{hora_envio}
chave_nivel_1   = chave_raiz|{campo_local_1}|{campo_local_2}
chave_nivel_2   = chave_raiz|{campo_local_1}|{campo_local_2}|{campo_local_3}|{campo_local_4}
```

**Regras de composição:**

| Regra | Detalhe |
|---|---|
| Separador | `\|` (pipe) — mesmo caractere do formato do arquivo |
| Identificador declarante | CNPJ ou código fiscal sem máscara (só dígitos) |
| Datas | Formato `AAAAMMDD` sem separadores |
| Horas | Formato `HHMMSS` sem separadores |
| Tipo | String/Varchar — nunca numérico, pois CNPJ começa com zeros |

**Por que incluir data e hora na chave raiz?**

Um mesmo declarante pode enviar o arquivo mais de uma vez (retificação, reenvio). A data e hora de
transmissão diferenciam cada envio, evitando colisão entre versões do mesmo período.

---

## 3. Chave Estrangeira (FK) nos Filhos

Cada registro filho recebe, além dos seus campos nativos, uma FK que aponta para a chave do pai
imediato e, opcionalmente, para o ancestral raiz:

```
registro_filho = {
    ...campos_nativos...,
    chave_pai_nivel_n   : chave_nivel_n,     ← FK para o pai direto
    chave_pai_raiz      : chave_raiz,        ← FK para o ancestral raiz (opcional)
}
```

Isso permite JOIN direto entre qualquer nível sem navegação transativa pela hierarquia, o que é
especialmente relevante ao exportar para CSV ou carregar em banco de dados.

---

## 4. Implementação: Estado Ativo (Context Tracking)

O parser mantém um **objeto de estado** que guarda o registro pai ativo em cada nível. Quando
um novo registro pai é encontrado, o estado é atualizado; quando um filho é encontrado, o estado
atual é injetado como referência.

```python
class Estado:
    pai_nivel_1: RegistroNivel1 | None = None
    pai_nivel_2: RegistroNivel2 | None = None

for linha in arquivo:
    tipo = linha[0]

    if tipo == NIVEL_1:
        estado.pai_nivel_1 = RegistroNivel1.from_campos(linha)
        estado.pai_nivel_2 = None  # reseta filho ao trocar o pai

    elif tipo == NIVEL_2:
        registro = RegistroNivel2.from_campos(linha, pai=estado.pai_nivel_1)
        estado.pai_nivel_2 = registro

    elif tipo == NIVEL_3:
        registro = RegistroNivel3.from_campos(linha, pai=estado.pai_nivel_2)
```

A referência ao pai é armazenada **dentro do dataclass filho** (campo `pai_nivel_n`). Isso garante
que qualquer código downstream acesse o contexto sem precisar de estado global.

---

## 5. Chave Postergada (Lazy Key)

Quando o identificador do nível raiz só está disponível em um registro subsequente (ex: o código
do declarante está no registro de cabeçalho, que vem depois do envelope de transmissão), a chave
deve ser **postergada**:

1. O registro de envelope é guardado em memória (`pendente`)
2. Quando o registro de cabeçalho é lido, o identificador é extraído
3. A chave completa é montada e injetada retroativamente no `pendente`
4. Ambos os registros são então emitidos/armazenados

```python
pendente = None

for linha in arquivo:
    if tipo == ENVELOPE:
        chave_parcial = f"{data}|{hora}"
        pendente = {"chave": chave_parcial, ...}

    elif tipo == CABECALHO:
        identificador = campos[POSICAO_CNPJ]
        chave_completa = f"{identificador}|{chave_parcial}"
        pendente["chave"] = chave_completa   # injeta retroativamente
        emitir(pendente)
        pendente = None
        emitir(cabecalho_com_chave_completa)
```

---

## 6. Validação por Comparação de Somas

Arquivos fiscais hierárquicos frequentemente incluem campos de totalizador nos níveis intermediários
(ex: valor total do mês no nível de resumo mensal). A validação consiste em comparar o valor
declarado no pai com a soma calculada a partir dos filhos:

```
soma_filhos = Σ valor(filho_i)   ∀ filho_i ∈ filhos(pai)
divergencia = declarado_pai - soma_filhos
```

**Implementação em streaming (sem armazenar todos os registros):**

```python
acumuladores = {}   # chave_pai → {declarado, soma_filhos}

for linha em arquivo:
    if tipo == PAI:
        acumuladores[chave] = {"declarado": valor, "soma": Decimal("0")}

    elif tipo == FILHO:
        acumuladores[chave_pai]["soma"] += valor_filho

# Ao final: compara declarado vs soma para cada chave
for chave, d in acumuladores.items():
    divergencia = d["declarado"] - d["soma"]
```

Essa abordagem consome memória O(n_pais), não O(n_filhos), o que é eficiente para arquivos com
muitas transações por grupo.

---

## 7. Reuso para EFD e outros leiautes SPED

O padrão descrito neste documento é independente do leiaute específico. Para adaptar a outro
arquivo fiscal:

| Passo | Ação |
|---|---|
| 1 | Identificar os níveis hierárquicos do leiaute (ex: blocos do EFD) |
| 2 | Mapear qual campo de cada nível é o identificador local |
| 3 | Definir o identificador raiz (CNPJ + data/hora de transmissão) |
| 4 | Criar dataclasses para cada nível com campo `pai` apontando para o nível anterior |
| 5 | Implementar `Estado` com os pais ativos em cada nível |
| 6 | Em `serializar_registro`, injetar `chave_pai_*` usando a mesma lógica de prefixo |
| 7 | Em `gerar_comparacao`, usar acumuladores por nível para validar totalizadores |

**Identifique no leiaute oficial:**
- O registro que contém o CNPJ do declarante (geralmente abertura do bloco 0)
- O registro de envelope/protocolo com data e hora de transmissão
- Os campos de valor totalizador em cada nível intermediário
- Os campos que formam a chave natural de cada nível (o que torna um registro único dentro do arquivo)
