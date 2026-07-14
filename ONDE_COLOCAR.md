# ONDE COLOCAR CADA ARQUIVO — repositório gabrielsbrasil/consumo-de-aulas

Tudo o que você precisa está dentro do `consumo-de-aulas.zip`.
Extraia o ZIP e suba o conteúdo EXATAMENTE nesta estrutura:

```
consumo-de-aulas/            (raiz do repositório)
│
├── index.html               ← SUBSTITUI o que está lá (dashboard novo)
├── gerar_data.py            ← SUBSTITUI (pipeline calibrado com seus dados)
├── README.md                ← SUBSTITUI
│
├── .github/
│   └── workflows/
│       └── atualizar.yml    ← a automação (roda a cada upload + diariamente)
│
└── dados/
    ├── v2_membros.csv           ← seu V2 (já renomeado, dentro do ZIP)
    ├── consumo_curseduca.csv    ← seu report (já renomeado, dentro do ZIP)
    └── dominios_extra.csv       ← vínculos manuais dominio;empresa
```

## Passo a passo (5 min)

1. Extraia o `consumo-de-aulas.zip` no seu Mac.
2. No Finder, aperte **Cmd + Shift + .** (ponto) para exibir a pasta
   oculta `.github`.
3. Abra github.com/gabrielsbrasil/consumo-de-aulas
   → **Add file → Upload files**.
4. Arraste TODO o conteúdo da pasta extraída (os 3 arquivos da raiz
   + as pastas `.github` e `dados`) e confirme o commit.
   O GitHub substitui os arquivos antigos automaticamente.
5. Crie o segredo (se ainda não criou):
   **Settings → Secrets and variables → Actions → New repository secret**
   - Name:   DASHBOARD_SALT
   - Secret: ce7ccda0e0197e3e8b09f2190979420a

## O que acontece depois do upload

- O Actions roda sozinho (aba **Actions** mostra a execução).
- Ele cria a pasta `data/` com os 347 arquivos criptografados.
- Em Actions → execução → **Artifacts** ficam:
  - `chaves_acesso`   → Empresa;CSM;Chave;Link (para distribuir)
  - `nao_vinculados`  → domínios sem empresa (para revisar)
- Teste com uma chave real do chaves_acesso.csv:
  https://gabrielsbrasil.github.io/consumo-de-aulas/?empresa=CHAVE

## O que você NÃO precisa subir

- chaves_acesso.csv   (interno — o Actions gera como artifact)
- nao_vinculados.csv  (idem)
- gerar_tokens.py     (obsoleto — pode até apagar do repo se estiver lá)
- pasta data/         (o Actions cria e atualiza sozinho)

## Rotina diária (depois de instalado)

Só atualizar os CSVs em `dados/` pelo próprio GitHub
(Add file → Upload files dentro da pasta dados/):
- novo export do V2      → renomear para  v2_membros.csv
- novo report Curseduca  → renomear para  consumo_curseduca.csv
- presença de lives      → aulas_ao_vivo.csv  (email;aula;data)

O resto é automático.
