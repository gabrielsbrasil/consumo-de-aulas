#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_data.py — Pipeline de dados do Dashboard de Consumo de Aulas
==================================================================
Adaptado aos formatos REAIS da PipeLovers:

Entradas (pasta dados/):
  v2_membros.csv          (obrigatório)  Export V2 "Base de Membros - CLIENTES B2B"
                                         -> empresas ATIVAS (col 'ead') + CSM (col 'CSM')
  consumo_curseduca.csv   (obrigatório)  Report Curseduca: Evento;Nome;Email;Conteúdo;Data
                                         -> data no formato DD/MM/AAAA HH:MM
  aulas_ao_vivo.csv       (opcional)     email;aula;data -> presença nas aulas ao vivo
  dominios_extra.csv      (opcional)     dominio;empresa -> exceções de vínculo
                                         (ex.: ogbroking.com;OG Broking)

Vínculo usuário -> empresa:
  1. dominios_extra.csv (exceções manuais têm prioridade)
  2. match automático: domínio do email vs nome da empresa ('ead')
  Emails genéricos (gmail, hotmail...) e internos (pipelovers.net, teste...)
  só entram via dominios_extra.csv.

Saídas:
  data/{hash}.json     -> um arquivo CRIPTOGRAFADO (AES-256-GCM) por empresa
  chaves_acesso.csv    -> Empresa;CSM;Chave;Link (artifact interno — NÃO commitar)
  nao_vinculados.csv   -> domínios corporativos sem empresa (para revisar)

Segurança:
  - SALT vem da variável de ambiente DASHBOARD_SALT (GitHub Secret).
  - Nome do arquivo = hash da chave: não revela a chave nem a empresa.
"""

import base64
import csv
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ============================================================
# CONFIGURAÇÃO
# ============================================================

SALT = os.environ.get("DASHBOARD_SALT", "").strip()
TAMANHO_CHAVE = 12
URL_BASE = "https://gabrielsbrasil.github.io/consumo-de-aulas/"

DIR_DADOS = Path("dados")
DIR_SAIDA = Path("data")

# Status considerados no V2
STATUS_VALIDOS = {"ativo"}

# Conteúdos do report que NÃO são aulas (matrículas em curso/módulo/trilha)
PREFIXOS_NAO_AULA = ("modulo", "módulo", "programa", "inicie sua jornada",
                     "certificacao", "certificação")

# Domínios que nunca vinculam automaticamente (só via dominios_extra.csv)
DOMINIOS_GENERICOS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.br",
    "icloud.com", "live.com", "bol.com.br", "uol.com.br", "terra.com.br",
    "protonmail.com", "me.com", "msn.com",
}
DOMINIOS_INTERNOS = {
    "pipelovers.net", "pipelovers.com", "teste.com", "curseduca.com",
    "canais.com", "prevendas.com", "img.com.br", "example.com",
}

# ============================================================
# HELPERS
# ============================================================

def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def slug(t: str) -> str:
    """Normaliza para comparação de domínio: minúsculo, sem acento,
    só letras e números."""
    return re.sub(r"[^a-z0-9]", "", norm(t))


def gerar_chave(empresa: str) -> str:
    base = f"{SALT}|{norm(empresa)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:TAMANHO_CHAVE]


def nome_arquivo(chave: str) -> str:
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()[:16] + ".json"


def criptografar(chave: str, obj: dict) -> dict:
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100_000)
    key = kdf.derive(chave.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"salt": b64(salt), "iv": b64(iv), "data": b64(ct)}


def ler_csv(caminho: Path) -> tuple[list[dict], list[str]]:
    raw = caminho.read_text(encoding="utf-8-sig", errors="replace")
    linhas = raw.splitlines()
    if not linhas:
        return [], []
    sep = ";" if linhas[0].count(";") >= linhas[0].count(",") else ","
    reader = csv.DictReader(linhas, delimiter=sep)
    # normaliza espaços nos nomes de coluna (' Status' -> 'Status')
    rows = []
    for r in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
    header = [(h or "").strip() for h in (reader.fieldnames or [])]
    return rows, header


def normalizar_data(valor: str) -> str | None:
    """'DD/MM/AAAA HH:MM' ou 'DD/MM/AAAA' ou 'AAAA-MM-DD' -> 'AAAA-MM-DD'."""
    v = str(valor).strip().split(" ")[0].split("T")[0]
    if not v:
        return None
    if "/" in v:
        p = v.split("/")
        if len(p) == 3:
            d, m, y = p
            if len(y) == 2:
                y = "20" + y
            return f"{y}-{int(m):02d}-{int(d):02d}"
    if "-" in v and len(v.split("-")[0]) == 4:
        p = v.split("-")
        if len(p) == 3:
            return f"{p[0]}-{int(p[1]):02d}-{int(p[2]):02d}"
    return None


def eh_aula(conteudo: str) -> bool:
    """Filtra matrículas em módulos/programas/trilhas — só títulos de aula contam."""
    c = norm(conteudo)
    return bool(c) and not c.startswith(PREFIXOS_NAO_AULA)


# ============================================================
# PIPELINE
# ============================================================

def main():
    if not SALT:
        print("[ERRO] Variável de ambiente DASHBOARD_SALT não definida.")
        print("       GitHub: Settings -> Secrets and variables -> Actions -> New repository secret")
        sys.exit(1)

    # ---------- 1. Empresas ativas + CSM (V2) ----------
    arq = DIR_DADOS / "v2_membros.csv"
    if not arq.exists():
        print(f"[ERRO] {arq} não encontrado."); sys.exit(1)
    linhas, header = ler_csv(arq)
    for col in ("ead", "Status", "CSM"):
        if col not in header:
            print(f"[ERRO] Coluna '{col}' não encontrada no V2. Colunas: {header[:10]}...")
            sys.exit(1)

    empresas = {}    # norm(nome) -> {"nome", "csm"}
    for r in linhas:
        if norm(r.get("Status", "")) not in STATUS_VALIDOS:
            continue
        nome = r.get("ead", "").strip()
        if not nome:
            continue
        empresas[norm(nome)] = {"nome": nome, "csm": r.get("CSM", "").strip() or "PipeLovers"}
    print(f"Empresas ativas no V2: {len(empresas)}")

    # slugs para match por domínio
    emp_slugs = {slug(info["nome"]): key for key, info in empresas.items() if slug(info["nome"])}

    # ---------- 2. Exceções de domínio (opcional) ----------
    dominio_para_emp = {}   # dominio -> norm(nome empresa)
    arq_dom = DIR_DADOS / "dominios_extra.csv"
    if arq_dom.exists():
        linhas_d, _ = ler_csv(arq_dom)
        for r in linhas_d:
            vals = list(r.values())
            if len(vals) < 2:
                continue
            dom, emp = norm(vals[0]), norm(vals[1])
            if dom and emp in empresas:
                dominio_para_emp[dom] = emp
            elif dom and emp:
                print(f"[aviso] dominios_extra: empresa '{vals[1]}' não está ativa no V2 — ignorada.")
        print(f"Exceções de domínio: {len(dominio_para_emp)}")

    def empresa_do_email(email: str) -> str | None:
        """Retorna norm(nome) da empresa ou None."""
        dom = email.split("@")[-1].lower().strip()
        if dom in dominio_para_emp:
            return dominio_para_emp[dom]
        if dom in DOMINIOS_GENERICOS or dom in DOMINIOS_INTERNOS:
            return None
        base = slug(dom.split(".")[0])
        if not base:
            return None
        # match exato do primeiro nível do domínio com o slug da empresa
        if base in emp_slugs:
            return emp_slugs[base]
        # match por prefixo (ex.: 'zoho' -> 'zohocorp'), mínimo 4 chars
        for s, key in emp_slugs.items():
            if len(s) >= 4 and (base.startswith(s) or s.startswith(base)):
                return key
        # match por contenção (ex.: 'redeimagem' in 'grupo redeimagem'), mínimo 5 chars
        for s, key in emp_slugs.items():
            if len(s) >= 5 and (s in base or base in s):
                return key
        return None

    # ---------- 3. Consumo (Curseduca + aulas ao vivo) ----------
    consumo = {}          # email -> [{"t","d"}]
    nomes = {}            # email -> nome mais recente
    dominios_orfaos = Counter()

    def registrar(email, nome, aula, data):
        email = email.lower().strip()
        if not (email and "@" in email and aula and data):
            return
        consumo.setdefault(email, []).append({"t": aula, "d": data})
        if nome:
            nomes.setdefault(email, nome)

    arq_c = DIR_DADOS / "consumo_curseduca.csv"
    if not arq_c.exists():
        print(f"[ERRO] {arq_c} não encontrado."); sys.exit(1)
    linhas_c, header_c = ler_csv(arq_c)
    for col in ("Email", "Conteúdo", "Data"):
        if col not in header_c:
            print(f"[ERRO] Coluna '{col}' não encontrada no report. Colunas: {header_c}")
            sys.exit(1)
    n_validos, n_filtrados = 0, 0
    for r in linhas_c:
        conteudo = r.get("Conteúdo", "").strip()
        if not eh_aula(conteudo):
            n_filtrados += 1
            continue
        data = normalizar_data(r.get("Data", ""))
        registrar(r.get("Email", ""), r.get("Nome", "").strip(), conteudo, data)
        n_validos += 1
    print(f"Report Curseduca: {n_validos} aulas válidas | {n_filtrados} matrículas de curso/módulo filtradas")

    arq_v = DIR_DADOS / "aulas_ao_vivo.csv"
    if arq_v.exists():
        linhas_v, header_v = ler_csv(arq_v)
        mapa = {norm(h): h for h in header_v}
        c_mail = mapa.get("email") or mapa.get("e-mail")
        c_aula = mapa.get("aula") or mapa.get("conteudo") or mapa.get("titulo")
        c_data = mapa.get("data") or mapa.get("data da aula")
        c_nome = mapa.get("nome")
        if not (c_mail and c_aula and c_data):
            print(f"[ERRO] aulas_ao_vivo.csv precisa das colunas email;aula;data. Encontradas: {header_v}")
            sys.exit(1)
        n = 0
        for r in linhas_v:
            data = normalizar_data(r.get(c_data, ""))
            registrar(r.get(c_mail, ""), r.get(c_nome, "").strip() if c_nome else "",
                      r.get(c_aula, "").strip(), data)
            n += 1
        print(f"Aulas ao vivo: {n} registros")
    else:
        print("[info] dados/aulas_ao_vivo.csv ausente — pulando aulas ao vivo.")

    # dedup por (email, aula, dia)
    for email, lst in consumo.items():
        vistos, dedup = set(), []
        for item in sorted(lst, key=lambda x: x["d"], reverse=True):
            k = (norm(item["t"]), item["d"])
            if k not in vistos:
                vistos.add(k); dedup.append(item)
        consumo[email] = dedup

    # ---------- 4. Vincular usuários às empresas ----------
    por_empresa = {}      # norm(nome) -> {email: user}
    vinculados, sem_vinculo = 0, 0
    for email, lessons in consumo.items():
        key = empresa_do_email(email)
        if key is None:
            dom = email.split("@")[-1]
            if dom not in DOMINIOS_GENERICOS and dom not in DOMINIOS_INTERNOS:
                dominios_orfaos[dom] += len(lessons)
            sem_vinculo += 1
            continue
        por_empresa.setdefault(key, {})[email] = {
            "name": nomes.get(email, email.split("@")[0].replace(".", " ").title()),
            "email": email,
            "lessons": lessons,
        }
        vinculados += 1
    print(f"Usuários vinculados a empresas ativas: {vinculados} | sem vínculo: {sem_vinculo}")

    # relatório de domínios corporativos órfãos (para alimentar dominios_extra.csv)
    with open("nao_vinculados.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Domínio", "Aulas consumidas", "Sugestão"])
        for dom, cnt in dominios_orfaos.most_common():
            w.writerow([dom, cnt, "adicionar em dados/dominios_extra.csv se for cliente"])
    print(f"Domínios corporativos sem vínculo: {len(dominios_orfaos)} (ver nao_vinculados.csv)")

    # ---------- 5. Gerar 1 JSON criptografado por empresa ativa ----------
    DIR_SAIDA.mkdir(exist_ok=True)
    for f in DIR_SAIDA.glob("*.json"):
        f.unlink()

    chaves = []
    for key in sorted(empresas):
        info = empresas[key]
        chave = gerar_chave(info["nome"])
        users = sorted(por_empresa.get(key, {}).values(), key=lambda u: norm(u["name"]))
        payload = {"company": info["nome"], "csm": info["csm"], "users": users}
        (DIR_SAIDA / nome_arquivo(chave)).write_text(
            json.dumps(criptografar(chave, payload), ensure_ascii=False), encoding="utf-8")
        chaves.append((info["nome"], info["csm"], chave))
    print(f"JSONs criptografados gerados: {len(chaves)} em {DIR_SAIDA}/")

    # ---------- 6. chaves_acesso.csv (interno — NÃO commitar) ----------
    with open("chaves_acesso.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Empresa", "CSM", "Chave", "Link"])
        for emp, csm, ch in chaves:
            w.writerow([emp, csm, ch, f"{URL_BASE}?empresa={ch}"])
    print("chaves_acesso.csv gerado (interno).")


if __name__ == "__main__":
    main()
