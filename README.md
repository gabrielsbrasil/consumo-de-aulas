# Dashboard de Consumo de Aulas — Clientes PipeLovers

Dashboard online para clientes B2B acompanharem o consumo de aulas da equipe:
aulas consumidas por mês, usuários vinculados e histórico de aulas por usuário.

**URL:** `https://gabrielsbrasil.github.io/consumo-de-aulas/`

## Acesso por cliente

Cada empresa recebe uma **chave única**. O acesso é feito via link:

```
https://gabrielsbrasil.github.io/consumo-de-aulas/?empresa=CHAVE
```

Uma empresa nunca enxerga os dados de outra: o dashboard só carrega os dados
correspondentes à chave informada.

## Arquivos

| Arquivo | Função |
|---|---|
| `index.html` | O dashboard (arquivo único, sem dependências de build) |
| `gerar_tokens.py` | Gera a chave de cada empresa e o `chaves_acesso.csv` (Empresa;Chave;Link) |

## Chaves de acesso

As chaves são **determinísticas**: geradas por hash do nome da empresa + SALT
secreto. Rodar o script de novo gera as mesmas chaves — os links enviados aos
clientes nunca quebram.

⚠️ **Nunca altere o `SALT` no `gerar_tokens.py` depois de distribuir os links**
(isso mudaria todas as chaves). O `chaves_acesso.csv` gerado é de uso interno
(gestor + CSMs) e **não deve ser commitado neste repositório**.

## Atualização de dados

Etapa em construção: script Python que cruza a base de aulas da Curseduca com
o consumo de aulas ao vivo e gera um JSON por empresa (nomeado pela chave),
atualizado diariamente via GitHub Actions a partir do `grupos_acesso.csv`.

## Chaves de teste (dados fictícios)

Enquanto os dados reais não são plugados, o `index.html` contém dados de exemplo:

- `a7f3k9x2` → Checklist Fácil
- `demo1234` → Empresa Demo
