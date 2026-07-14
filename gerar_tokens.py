#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de chaves de acesso — Dashboard de Consumo de Aulas PipeLovers
======================================================================
Gera uma chave determinística por empresa e exporta o mapeamento
Empresa -> Chave -> Link em CSV (; UTF-8-sig, pronto p/ Excel PT-BR).

Determinística = rodar de novo gera a MESMA chave (links nunca quebram),
desde que o SALT não mude.

Uso:
    python3 gerar_tokens.py grupos_acesso.csv

Entrada esperada (grupos_acesso.csv): qualquer CSV com uma coluna de
nome da empresa (por padrão procura 'nome', 'empresa' ou 'grupo';
ajuste COLUNA_EMPRESA se necessário).

Saída:
    chaves_acesso.csv  -> Empresa;Chave;Link
"""

import csv
import hashlib
import sys
import unicodedata
from pathlib import Path

# ============================================================
# CONFIGURAÇÃO
# ============================================================

# SALT secreto: NUNCA compartilhe e NUNCA mude depois de distribuir
# os links (mudar o salt muda todas as chaves).
SALT = "TROQUE-POR-UM-SEGREDO-SEU-2026"

# Tamanho da chave (12 chars ~ 62^12 combinações se alfanumérico;
# aqui usamos hex truncado: 12 chars = 16^12 ≈ 2,8e14 — suficiente
# para impedir adivinhação entre ~350 empresas).
TAMANHO_CHAVE = 12

# URL base onde o dashboard estará hospedado (GitHub Pages)
URL_BASE = "https://gabrielsbrasil.github.io/consumo-de-aulas/"

# Nome da coluna com o nome da empresa no CSV de entrada.
# Deixe None para autodetectar ('nome', 'empresa', 'grupo', 'nome fantasia').
COLUNA_EMPRESA = None

CANDIDATAS = ["nome fantasia", "nome_fantasia", "empresa", "nome", "grupo", "grupos de acesso", "grupo de acesso"]

# ============================================================


def normalizar(texto: str) -> str:
    """Normaliza o nome da empresa para gerar chave estável
    (sem acento, minúsculo, espaços colapsados)."""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def gerar_chave(empresa: str) -> str:
    """Chave determinística: sha256(salt + nome normalizado), truncada."""
    base = f"{SALT}|{normalizar(empresa)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:TAMANHO_CHAVE]


def detectar_coluna(header: list[str]) -> str:
    if COLUNA_EMPRESA:
        return COLUNA_EMPRESA
    lower = {h.lower().strip(): h for h in header}
    for cand in CANDIDATAS:
        if cand in lower:
            return lower[cand]
    # fallback: primeira coluna
    print(f"[aviso] Nenhuma coluna candidata encontrada; usando a primeira: '{header[0]}'")
    return header[0]


def ler_empresas(caminho: Path) -> list[str]:
    """Lê o CSV detectando separador (; ou ,) e retorna nomes únicos."""
    raw = caminho.read_text(encoding="utf-8-sig", errors="replace")
    sep = ";" if raw.splitlines()[0].count(";") >= raw.splitlines()[0].count(",") else ","
    reader = csv.DictReader(raw.splitlines(), delimiter=sep)
    col = detectar_coluna(reader.fieldnames)
    vistos, empresas = set(), []
    for row in reader:
        nome = (row.get(col) or "").strip()
        if not nome:
            continue
        chave_norm = normalizar(nome)
        if chave_norm not in vistos:
            vistos.add(chave_norm)
            empresas.append(nome)
    return empresas


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 gerar_tokens.py grupos_acesso.csv")
        sys.exit(1)

    entrada = Path(sys.argv[1])
    if not entrada.exists():
        print(f"Arquivo não encontrado: {entrada}")
        sys.exit(1)

    empresas = ler_empresas(entrada)
    print(f"{len(empresas)} empresas únicas encontradas.")

    # Verificação de colisão (extremamente improvável, mas checamos)
    chaves = {}
    for emp in empresas:
        ch = gerar_chave(emp)
        if ch in chaves:
            print(f"[ERRO] Colisão de chave entre '{chaves[ch]}' e '{emp}'. "
                  f"Aumente TAMANHO_CHAVE.")
            sys.exit(1)
        chaves[ch] = emp

    saida = Path("chaves_acesso.csv")
    with saida.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Empresa", "Chave", "Link"])
        for emp in sorted(empresas, key=normalizar):
            ch = gerar_chave(emp)
            w.writerow([emp, ch, f"{URL_BASE}?empresa={ch}"])

    print(f"OK -> {saida} (Empresa;Chave;Link, UTF-8-sig, separador ';')")


if __name__ == "__main__":
    main()
