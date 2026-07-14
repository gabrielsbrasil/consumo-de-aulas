# Dashboard de Consumo de Aulas — Clientes PipeLovers

Dashboard online para clientes B2B acompanharem o consumo de aulas da equipe:
aulas consumidas por mês, usuários vinculados e histórico de aulas por usuário.

**URL:** `https://gabrielsbrasil.github.io/consumo-de-aulas/`

## Acesso por cliente

Cada empresa recebe uma **chave única**. O acesso é feito via link:

```
https://gabrielsbrasil.github.io/consumo-de-aulas/?empresa=CHAVE
```

Uma empresa nunca enxerga os dados de outra: os dados de cada conta ficam em
um arquivo **criptografado** (AES-256) que só abre com a chave correta.

## Arquivos

| Arquivo | Função |
|---|---|
| `index.html` | O dashboard (arquivo único, sem dependências de build) |
| `gerar_data.py` | Pipeline: lê os CSVs de `dados/` e gera os arquivos criptografados em `data/` |
| `.github/workflows/atualizar.yml` | Automação: roda o pipeline a cada upload em `dados/` e diariamente |

## Atualização de dados (rotina)

Fluxo: subir os CSVs na pasta `dados/` → o GitHub Actions roda `gerar_data.py`
→ gera um JSON criptografado por empresa em `data/` → o dashboard mostra os
dados novos automaticamente.

Arquivos de entrada (pasta `dados/`):

| Arquivo | Obrigatório | Conteúdo |
|---|---|---|
| `grupos_acesso.csv` | Sim | `codigo;nome` — lista de empresas clientes |
| `membros.csv` | Sim | `nome;email;grupos` — usuário → empresa |
| `consumo_curseduca.csv` | Sim | `email;aula;data;origem` — consumo gravado |
| `aulas_ao_vivo.csv` | Não | `email;aula;data` — presença nas aulas ao vivo |
| `csms.csv` | Não | `empresa;csm` — CSM responsável por conta |

Linhas com origem "Importação em lote" são ignoradas (histórico duplicado do
Hubla). Datas aceitas: `AAAA-MM-DD` ou `DD/MM/AAAA`. Nomes de coluna e
separador (`;` ou `,`) são autodetectados.

## Chaves de acesso

As chaves são **determinísticas**: hash do nome da empresa + SALT secreto
(GitHub Secret `DASHBOARD_SALT`). Rodar o pipeline de novo gera as mesmas
chaves — os links enviados aos clientes nunca quebram.

Para consultar as chaves: aba **Actions → última execução → Artifacts →
`chaves_acesso`** (CSV `Empresa;Chave;Link`, visível só para quem tem acesso
ao repositório — nunca é commitado).

⚠️ **Nunca altere o `DASHBOARD_SALT` depois de distribuir os links** (isso
mudaria todas as chaves de todas as empresas).

## Chaves de teste (dados fictícios)

- `a7f3k9x2` → Checklist Fácil
- `demo1234` → Empresa Demo
