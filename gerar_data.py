#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_data.py - Pipeline de dados do Dashboard de Consumo de Aulas
==================================================================
NOVO MODELO (base relacional por ID):

Entradas (pasta dados/):
  contas.csv           (obrigatorio) nome;created_at;id
                        -> uma linha por EMPRESA/CONTA cliente (o "id" e a conta_id)
  usuarios.csv         (obrigatorio) id;created_at;nome;email;whatsapp;status;id_conta;cargo;data_criacao
                        -> uma linha por USUARIO; id_conta liga o usuario a uma conta de contas.csv
  empresas.csv         (obrigatorio) id;created_at;tipo_contrato;csm;data_assinatura;data_churn;conta_id
                        -> contratos/historico por conta; traz o CSM e o status (ativo/churn)
  consumo_curseduca.csv(obrigatorio) Report Curseduca: Evento;Nome;Email;Conteudo;Data
                        -> data no formato DD/MM/AAAA HH:MM
  aulas_ao_vivo.csv    (opcional)    email;aula;data -> presenca nas aulas ao vivo

Vinculo usuario -> empresa:
  Feito por ID (usuarios.id_conta == contas.id). NAO ha mais adivinhacao por dominio de email.
  O consumo (Curseduca / aulas ao vivo) e cruzado com o usuario pelo EMAIL.

Saidas:
  data/{hash}.json  -> um arquivo CRIPTOGRAFADO (AES-256-GCM) por empresa
  chaves_acesso.csv -> Empresa;CSM;Chave;Link (artifact interno - NAO commitar)

Chaves de acesso (NAO MUDAM):
  A chave e derivada de sha256(SALT | nome_normalizado_da_empresa), igual a versao
  anterior. Enquanto o NOME da conta em contas.csv for o mesmo usado antes, a chave
  e o link de cada cliente permanecem identicos.

Seguranca:
  - SALT vem da variavel de ambiente DASHBOARD_SALT (GitHub Secret).
  - Nome do arquivo = hash da chave: nao revela a chave nem a empresa.
"""

import base64
import csv
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ============================================================
# CONFIGURACAO
# ============================================================

SALT = os.environ.get("DASHBOARD_SALT", "").strip()
TAMANHO_CHAVE = 12
URL_BASE = "https://gabrielsbrasil.github.io/consumo-de-aulas/"

DIR_DADOS = Path("dados")
DIR_SAIDA = Path("data")

# Conteudos do report que NAO sao aulas (matriculas em curso/modulo/trilha)
PREFIXOS_NAO_AULA = ("modulo", "programa", "inicie sua jornada",
                     "certificacao")

# ============================================================
# HELPERS
# ============================================================

def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())

def gerar_chave(empresa: str) -> str:
    # IDENTICO a versao anterior: a chave (e portanto a URL do cliente)
    # depende apenas do SALT e do nome normalizado da empresa.
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
    rows = []
    for r in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
    header = [(h or "").strip() for h in (reader.fieldnames or [])]
    return rows, header

def achar_arquivo(*nomes: str) -> Path | None:
    """Aceita variacoes de nome (contas.csv/conta.csv, usuarios.csv/usuario.csv...)."""
    for n in nomes:
        p = DIR_DADOS / n
        if p.exists():
            return p
    return None

def col(header: list[str], *alvos: str) -> str | None:
    mapa = {norm(h): h for h in header}
    for a in alvos:
        if norm(a) in mapa:
            return mapa[norm(a)]
    return None

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
            try:
                return f"{y}-{int(m):02d}-{int(d):02d}"
            except ValueError:
                return None
    if "-" in v and len(v.split("-")[0]) == 4:
        p = v.split("-")
        if len(p) == 3:
            try:
                return f"{p[0]}-{int(p[1]):02d}-{int(p[2]):02d}"
            except ValueError:
                return None
    return None

def eh_aula(conteudo: str) -> bool:
    c = norm(conteudo)
    return bool(c) and not c.startswith(PREFIXOS_NAO_AULA)

# ============================================================
# PIPELINE
# ============================================================

def main():
    if not SALT:
        print("[ERRO] Variavel de ambiente DASHBOARD_SALT nao definida.")
        print("       GitHub: Settings -> Secrets and variables -> Actions -> New repository secret")
        sys.exit(1)

    # ---------- 1. Contas (empresas) ----------
    arq_contas = achar_arquivo("contas.csv", "conta.csv")
    if not arq_contas:
        print(f"[ERRO] dados/contas.csv nao encontrado."); sys.exit(1)
    linhas_c, header_c = ler_csv(arq_contas)
    c_id = col(header_c, "id")
    c_nome = col(header_c, "nome", "empresa", "conta")
    if not (c_id and c_nome):
        print(f"[ERRO] contas.csv precisa das colunas 'nome' e 'id'. Colunas: {header_c}")
        sys.exit(1)

    contas = {}   # conta_id (str) -> {"nome"}
    for r in linhas_c:
        cid = r.get(c_id, "").strip()
        nome = r.get(c_nome, "").strip()
        if cid and nome:
            contas[cid] = {"nome": nome}
    print(f"Contas carregadas: {len(contas)}")

    # ---------- 2. Empresas (CSM + contrato + status por conta) ----------
    arq_emp = achar_arquivo("empresas.csv", "empresa.csv")
    csm_por_conta = {}      # conta_id -> csm
    contrato_por_conta = {} # conta_id -> tipo_contrato
    ativo_por_conta = {}    # conta_id -> bool (sem data_churn = ativo)
    if arq_emp:
        linhas_e, header_e = ler_csv(arq_emp)
        e_conta = col(header_e, "conta_id", "id_conta")
        e_csm = col(header_e, "csm")
        e_contrato = col(header_e, "tipo_contrato", "contrato", "plano")
        e_assin = col(header_e, "data_assinatura")
        e_churn = col(header_e, "data_churn")
        if not e_conta:
            print(f"[ERRO] empresas.csv precisa da coluna 'conta_id'. Colunas: {header_e}")
            sys.exit(1)
        # varios contratos por conta: escolhe o mais recente por data_assinatura
        melhor = {}  # conta_id -> (chave_ordenacao, row)
        for r in linhas_e:
            cid = r.get(e_conta, "").strip()
            if not cid:
                continue
            ordem = r.get(e_assin, "") if e_assin else ""
            if cid not in melhor or ordem > melhor[cid][0]:
                melhor[cid] = (ordem, r)
        for cid, (_, r) in melhor.items():
            csm_por_conta[cid] = (r.get(e_csm, "").strip() if e_csm else "") or "PipeLovers"
            contrato_por_conta[cid] = r.get(e_contrato, "").strip() if e_contrato else ""
            churn = (r.get(e_churn, "").strip() if e_churn else "")
            ativo_por_conta[cid] = (churn == "")
        print(f"Contratos vinculados a contas: {len(melhor)}")
    else:
        print("[info] dados/empresas.csv ausente - seguindo sem CSM/contrato.")

    # ---------- 3. Usuarios (vinculo por id_conta) ----------
    arq_usr = achar_arquivo("usuarios.csv", "usuario.csv")
    if not arq_usr:
        print(f"[ERRO] dados/usuarios.csv nao encontrado."); sys.exit(1)
    linhas_u, header_u = ler_csv(arq_usr)
    u_email = col(header_u, "email", "e-mail")
    u_nome = col(header_u, "nome")
    u_conta = col(header_u, "id_conta", "conta_id")
    if not (u_email and u_conta):
        print(f"[ERRO] usuarios.csv precisa das colunas 'email' e 'id_conta'. Colunas: {header_u}")
        sys.exit(1)

    # email -> {conta_id, nome}
    usuarios = {}
    sem_conta = 0
    for r in linhas_u:
        email = r.get(u_email, "").lower().strip()
        cid = r.get(u_conta, "").strip()
        if not email or "@" not in email:
            continue
        if cid not in contas:
            sem_conta += 1
            continue
        usuarios[email] = {
            "conta_id": cid,
            "nome": (r.get(u_nome, "").strip() if u_nome else "") or email.split("@")[0].replace(".", " ").title(),
        }
    print(f"Usuarios vinculados a contas: {len(usuarios)} | usuarios sem conta valida: {sem_conta}")

    # ---------- 4. Consumo (Curseduca + aulas ao vivo), cruzado por email ----------
    consumo = {}   # email -> [{"t","d"}]
    nomes_consumo = {}

    def registrar(email, nome, aula, data):
        email = email.lower().strip()
        if not (email and "@" in email and aula and data):
            return
        consumo.setdefault(email, []).append({"t": aula, "d": data})
        if nome:
            nomes_consumo.setdefault(email, nome)

    arq_cur = achar_arquivo("consumo_curseduca.csv")
    if not arq_cur:
        print(f"[ERRO] dados/consumo_curseduca.csv nao encontrado."); sys.exit(1)
    linhas_cur, header_cur = ler_csv(arq_cur)
    k_email = col(header_cur, "Email", "e-mail")
    k_cont = col(header_cur, "Conteudo", "Conteúdo", "aula")
    k_data = col(header_cur, "Data")
    k_nome = col(header_cur, "Nome")
    if not (k_email and k_cont and k_data):
        print(f"[ERRO] consumo_curseduca.csv precisa de Email;Conteudo;Data. Colunas: {header_cur}")
        sys.exit(1)
    n_validos, n_filtrados = 0, 0
    for r in linhas_cur:
        conteudo = r.get(k_cont, "").strip()
        if not eh_aula(conteudo):
            n_filtrados += 1
            continue
        data = normalizar_data(r.get(k_data, ""))
        registrar(r.get(k_email, ""), (r.get(k_nome, "").strip() if k_nome else ""), conteudo, data)
        n_validos += 1
    print(f"Report Curseduca: {n_validos} aulas validas | {n_filtrados} matriculas filtradas")

    arq_v = achar_arquivo("aulas_ao_vivo.csv")
    if arq_v:
        linhas_v, header_v = ler_csv(arq_v)
        c_mail = col(header_v, "email", "e-mail")
        c_aula = col(header_v, "aula", "conteudo", "titulo")
        c_data = col(header_v, "data", "data da aula")
        c_nome = col(header_v, "nome")
        if not (c_mail and c_aula and c_data):
            print(f"[ERRO] aulas_ao_vivo.csv precisa de email;aula;data. Colunas: {header_v}")
            sys.exit(1)
        n = 0
        for r in linhas_v:
            data = normalizar_data(r.get(c_data, ""))
            registrar(r.get(c_mail, ""), (r.get(c_nome, "").strip() if c_nome else ""),
                      r.get(c_aula, "").strip(), data)
            n += 1
        print(f"Aulas ao vivo: {n} registros")
    else:
        print("[info] dados/aulas_ao_vivo.csv ausente - pulando aulas ao vivo.")

    # dedup por (email, aula, dia)
    for email, lst in consumo.items():
        vistos, dedup = set(), []
        for item in sorted(lst, key=lambda x: x["d"], reverse=True):
            k = (norm(item["t"]), item["d"])
            if k not in vistos:
                vistos.add(k); dedup.append(item)
        consumo[email] = dedup

    # ---------- 5. Montar usuarios por empresa ----------
    por_conta = {}  # conta_id -> {email: user}
    for email, info in usuarios.items():
        cid = info["conta_id"]
        por_conta.setdefault(cid, {})[email] = {
            "name": nomes_consumo.get(email, info["nome"]),
            "email": email,
            "lessons": consumo.get(email, []),
        }

    # ---------- 6. Gerar 1 JSON criptografado por conta ----------
    DIR_SAIDA.mkdir(exist_ok=True)
    for f in DIR_SAIDA.glob("*.json"):
        f.unlink()

    chaves = []
    for cid, info in sorted(contas.items(), key=lambda kv: norm(kv[1]["nome"])):
        nome = info["nome"]
        chave = gerar_chave(nome)          # <- chave/URL identica a antes
        csm = csm_por_conta.get(cid, "PipeLovers")
        users = sorted(por_conta.get(cid, {}).values(), key=lambda u: norm(u["name"]))
        payload = {
            "company": nome,
            "csm": csm,
            "contract": contrato_por_conta.get(cid, ""),
            "active": ativo_por_conta.get(cid, True),
            "users": users,
        }
        (DIR_SAIDA / nome_arquivo(chave)).write_text(
            json.dumps(criptografar(chave, payload), ensure_ascii=False), encoding="utf-8")
        chaves.append((nome, csm, chave))
    print(f"JSONs criptografados gerados: {len(chaves)} em {DIR_SAIDA}/")

    # ---------- 7. chaves_acesso.csv (interno - NAO commitar) ----------
    with open("chaves_acesso.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Empresa", "CSM", "Chave", "Link"])
        for emp, csm, ch in sorted(chaves):
            w.writerow([emp, csm, ch, f"{URL_BASE}?empresa={ch}"])
    print("chaves_acesso.csv gerado (interno).")

if __name__ == "__main__":
    main()
