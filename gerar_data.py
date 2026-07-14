#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_data.py — Pipeline de dados do Dashboard de Consumo de Aulas
==================================================================
Lê os CSVs da pasta dados/ e gera:
  - data/{hash-da-chave}.json  -> um arquivo CRIPTOGRAFADO por empresa
  - chaves_acesso.csv          -> Empresa;Chave;Link (NÃO commitar!)

Arquivos de entrada esperados em dados/:
  grupos_acesso.csv       (obrigatório)  código;nome  -> lista de empresas
  membros.csv             (obrigatório)  nome;email;grupos -> usuário → empresa
  consumo_curseduca.csv   (obrigatório)  email;aula;data -> consumo gravado
  aulas_ao_vivo.csv       (opcional)     email;aula;data -> presença ao vivo
  csms.csv                (opcional)     empresa;csm -> CSM responsável

Os nomes de coluna são autodetectados (várias variações aceitas).
Se algo não bater, o script imprime as colunas encontradas para ajuste.

Segurança:
  - O SALT vem da variável de ambiente DASHBOARD_SALT (GitHub Secret).
  - Cada JSON é criptografado (AES-256-GCM) com a chave da empresa.
  - O nome do arquivo é um hash da chave: quem navega no repo não
    consegue ler os dados nem descobrir as chaves.
"""

import base64
import csv
import hashlib
import json
import os
import sys
import unicodedata
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ============================================================
# CONFIGURAÇÃO
# ============================================================

SALT = os.environ.get("DASHBOARD_SALT", "").strip()
TAMANHO_CHAVE = 12          # deve ser igual ao gerar_tokens.py
URL_BASE = "https://gabrielsbrasil.github.io/consumo-de-aulas/"

DIR_DADOS = Path("dados")
DIR_SAIDA = Path("data")

# Candidatas de nomes de coluna (minúsculo, sem acento)
COLS_EMPRESA = ["nome fantasia", "nome_fantasia", "empresa", "nome", "grupo"]
COLS_CODIGO  = ["codigo", "código", "id", "cod"]
COLS_NOME    = ["nome", "aluno", "usuario", "usuário", "name"]
COLS_EMAIL   = ["email", "e-mail", "e_mail"]
COLS_GRUPOS  = ["grupos", "grupo", "grupos de acesso", "grupo de acesso", "turmas"]
COLS_AULA    = ["aula", "conteudo", "conteúdo", "licao", "lição", "titulo", "título", "nome da aula", "lesson"]
COLS_DATA    = ["data", "data de conclusao", "data de conclusão", "concluido em", "concluído em", "data consumo", "date", "data da aula"]
COLS_ORIGEM  = ["origem", "tipo", "fonte", "importacao", "importação"]
COLS_CSM     = ["csm", "responsavel", "responsável"]

# Linhas do consumo Curseduca a IGNORAR (histórico duplicado do Hubla)
ORIGENS_EXCLUIDAS = ["importacao em lote", "importação em lote"]

# ============================================================
# HELPERS
# ============================================================

def norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def gerar_chave(empresa: str) -> str:
    """Mesma lógica do gerar_tokens.py — chave determinística."""
    base = f"{SALT}|{norm(empresa)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:TAMANHO_CHAVE]


def nome_arquivo(chave: str) -> str:
    """Nome público do arquivo = hash da chave (não revela a chave)."""
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()[:16] + ".json"


def criptografar(chave: str, obj: dict) -> dict:
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100_000)
    key = kdf.derive(chave.encode("utf-8"))
    dados = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    ct = AESGCM(key).encrypt(iv, dados, None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"salt": b64(salt), "iv": b64(iv), "data": b64(ct)}


def ler_csv(caminho: Path) -> tuple[list[dict], list[str]]:
    """Lê CSV detectando separador; retorna (linhas, colunas)."""
    raw = caminho.read_text(encoding="utf-8-sig", errors="replace")
    linhas = raw.splitlines()
    if not linhas:
        return [], []
    primeira = linhas[0]
    sep = ";" if primeira.count(";") >= primeira.count(",") else ","
    reader = csv.DictReader(linhas, delimiter=sep)
    return list(reader), reader.fieldnames or []


def achar_coluna(header: list[str], candidatas: list[str], arquivo: str, obrigatoria=True):
    mapa = {norm(h): h for h in header}
    for cand in candidatas:
        if cand in mapa:
            return mapa[cand]
    if obrigatoria:
        print(f"[ERRO] Em {arquivo}: nenhuma coluna entre {candidatas}.")
        print(f"        Colunas encontradas: {header}")
        sys.exit(1)
    return None


def normalizar_data(valor: str) -> str | None:
    """Aceita 'YYYY-MM-DD', 'DD/MM/YYYY' (com ou sem hora) -> 'YYYY-MM-DD'."""
    v = str(valor).strip().split(" ")[0].split("T")[0]
    if not v:
        return None
    if "-" in v and len(v.split("-")[0]) == 4:
        p = v.split("-")
        if len(p) == 3:
            return f"{p[0]}-{p[1]:0>2}-{p[2]:0>2}"
    if "/" in v:
        p = v.split("/")
        if len(p) == 3:
            d, m, y = p
            if len(y) == 2:
                y = "20" + y
            return f"{y}-{m:0>2}-{d:0>2}"
    return None


# ============================================================
# PIPELINE
# ============================================================

def main():
    if not SALT:
        print("[ERRO] Variável de ambiente DASHBOARD_SALT não definida.")
        print("       No GitHub: Settings -> Secrets and variables -> Actions -> New repository secret")
        sys.exit(1)

    # ---------- 1. Empresas (grupos_acesso.csv) ----------
    arq = DIR_DADOS / "grupos_acesso.csv"
    if not arq.exists():
        print(f"[ERRO] {arq} não encontrado."); sys.exit(1)
    linhas, header = ler_csv(arq)
    col_emp = achar_coluna(header, COLS_EMPRESA, str(arq))
    col_cod = achar_coluna(header, COLS_CODIGO, str(arq), obrigatoria=False)

    empresas = {}          # norm(nome) -> nome oficial
    codigo_para_emp = {}   # código -> nome oficial
    for r in linhas:
        nome = (r.get(col_emp) or "").strip()
        if not nome:
            continue
        empresas[norm(nome)] = nome
        if col_cod and (r.get(col_cod) or "").strip():
            codigo_para_emp[str(r[col_cod]).strip()] = nome
    print(f"Empresas: {len(empresas)}")

    # ---------- 2. CSMs (opcional) ----------
    csm_por_emp = {}
    arq_csm = DIR_DADOS / "csms.csv"
    if arq_csm.exists():
        linhas, header = ler_csv(arq_csm)
        c_e = achar_coluna(header, COLS_EMPRESA, str(arq_csm))
        c_c = achar_coluna(header, COLS_CSM, str(arq_csm))
        for r in linhas:
            e, c = (r.get(c_e) or "").strip(), (r.get(c_c) or "").strip()
            if e and c:
                csm_por_emp[norm(e)] = c
        print(f"CSMs mapeados: {len(csm_por_emp)}")

    # ---------- 3. Membros (usuário -> empresa) ----------
    arq_m = DIR_DADOS / "membros.csv"
    if not arq_m.exists():
        print(f"[ERRO] {arq_m} não encontrado."); sys.exit(1)
    linhas, header = ler_csv(arq_m)
    c_nome = achar_coluna(header, COLS_NOME, str(arq_m))
    c_mail = achar_coluna(header, COLS_EMAIL, str(arq_m))
    c_grp  = achar_coluna(header, COLS_GRUPOS, str(arq_m))

    usuarios = {}   # email -> {"name","email","empresa"}
    sem_empresa = 0
    for r in linhas:
        email = (r.get(c_mail) or "").strip().lower()
        if not email:
            continue
        nome = (r.get(c_nome) or "").strip() or email
        grupos_raw = (r.get(c_grp) or "").strip()
        empresa = None
        # tenta casar cada grupo do usuário com uma empresa (por código ou nome)
        for g in [x.strip() for x in grupos_raw.replace("|", ",").split(",") if x.strip()]:
            if g in codigo_para_emp:
                empresa = codigo_para_emp[g]; break
            if norm(g) in empresas:
                empresa = empresas[norm(g)]; break
        if empresa is None:
            sem_empresa += 1
            continue
        usuarios[email] = {"name": nome, "email": email, "empresa": empresa}
    print(f"Membros vinculados: {len(usuarios)} | sem empresa correspondente: {sem_empresa}")

    # ---------- 4. Consumo (Curseduca + aulas ao vivo) ----------
    consumo = {}   # email -> [{"t": aula, "d": data}]

    def processar_consumo(caminho: Path, rotulo: str, obrigatorio: bool):
        if not caminho.exists():
            if obrigatorio:
                print(f"[ERRO] {caminho} não encontrado."); sys.exit(1)
            print(f"[info] {caminho} ausente — pulando {rotulo}.")
            return 0
        linhas, header = ler_csv(caminho)
        c_mail = achar_coluna(header, COLS_EMAIL, str(caminho))
        c_aula = achar_coluna(header, COLS_AULA, str(caminho))
        c_data = achar_coluna(header, COLS_DATA, str(caminho))
        c_orig = achar_coluna(header, COLS_ORIGEM, str(caminho), obrigatoria=False)
        n = 0
        for r in linhas:
            if c_orig and norm(r.get(c_orig) or "") in ORIGENS_EXCLUIDAS:
                continue
            email = (r.get(c_mail) or "").strip().lower()
            aula = (r.get(c_aula) or "").strip()
            data = normalizar_data(r.get(c_data) or "")
            if not (email and aula and data):
                continue
            consumo.setdefault(email, []).append({"t": aula, "d": data})
            n += 1
        print(f"{rotulo}: {n} registros válidos")
        return n

    processar_consumo(DIR_DADOS / "consumo_curseduca.csv", "Consumo Curseduca", obrigatorio=True)
    processar_consumo(DIR_DADOS / "aulas_ao_vivo.csv", "Aulas ao vivo", obrigatorio=False)

    # dedup por (email, aula, data)
    for email, lst in consumo.items():
        vistos, dedup = set(), []
        for item in sorted(lst, key=lambda x: x["d"], reverse=True):
            k = (norm(item["t"]), item["d"])
            if k not in vistos:
                vistos.add(k); dedup.append(item)
        consumo[email] = dedup

    # ---------- 5. Montar e criptografar 1 JSON por empresa ----------
    DIR_SAIDA.mkdir(exist_ok=True)
    # limpa arquivos antigos (empresas removidas somem)
    for f in DIR_SAIDA.glob("*.json"):
        f.unlink()

    por_empresa = {}
    for u in usuarios.values():
        por_empresa.setdefault(u["empresa"], []).append({
            "name": u["name"],
            "email": u["email"],
            "lessons": consumo.get(u["email"], [])
        })

    chaves = []
    for nome_norm, nome_oficial in sorted(empresas.items()):
        chave = gerar_chave(nome_oficial)
        payload = {
            "company": nome_oficial,
            "csm": csm_por_emp.get(nome_norm, "PipeLovers"),
            "users": sorted(por_empresa.get(nome_oficial, []), key=lambda u: norm(u["name"]))
        }
        arq_out = DIR_SAIDA / nome_arquivo(chave)
        arq_out.write_text(json.dumps(criptografar(chave, payload), ensure_ascii=False), encoding="utf-8")
        chaves.append((nome_oficial, chave))

    print(f"JSONs gerados: {len(chaves)} em {DIR_SAIDA}/")

    # ---------- 6. chaves_acesso.csv (uso interno — NÃO commitar) ----------
    with open("chaves_acesso.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Empresa", "Chave", "Link"])
        for emp, ch in chaves:
            w.writerow([emp, ch, f"{URL_BASE}?empresa={ch}"])
    print("chaves_acesso.csv gerado (interno).")


if __name__ == "__main__":
    main()
