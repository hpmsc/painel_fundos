#!/usr/bin/env python3
"""
montar.py — junta cadastro, classificações e execução orçamentária em site/dados.json.

Entradas (todas em dados/):
  fundos.csv              cadastro curado: identidade do fundo no painel e padrões
                          para reconhecer suas UOs no SIOP a cada exercício
  classificacoes.csv      histórico de classificações por fundo (ET 01/2026)
  marcos.csv              linha do tempo de normas, taxonomias e decisões (ET 01/2026)
  bruto/siop_AAAA.csv     execução por UO x fonte x RP x GND (gerado por coleta.R)
  semente_bassi_2018.csv  execução de 2018 (Bassi, TD Ipea 2458, Tabela 3), usada
                          apenas enquanto não houver siop_2018.csv

Não existe identificador único de fundo no orçamento. O painel usa o `id` do
cadastro como chave e registra, ano a ano, a combinação de identificadores
observada: UO(s) e fontes (do SIOP), UG/Gestão e CNPJ (do cadastro).

Uso: python3 montar.py [--saida site/dados.json]
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

DADOS = "dados"
METRICAS = ("ploa", "loa", "loa_mais_credito", "empenhado", "liquidado", "pago")
CURTO = {"ploa": "ploa", "loa": "loa", "loa_mais_credito": "atual",
         "empenhado": "emp", "liquidado": "liq", "pago": "pago"}


def norm(txt: str | None) -> str:
    txt = unicodedata.normalize("NFKD", txt or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt.upper()).strip()


def ler_csv(caminho: str) -> list[dict]:
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    for i, r in enumerate(linhas, start=2):
        if None in r:   # campo de texto com ";" sem aspas
            raise SystemExit(f"{caminho}, linha {i}: colunas a mais. Ponha entre aspas o texto que contém ';'.")
    return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in linhas]


def num(v) -> float:
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def eh_candidata(cod: str, desc: str) -> bool:
    return (len(cod) == 5 and cod[2] == "9") or "FUNDO" in norm(desc)


def dimensao_uo(cod: str) -> str:
    return "Financeira (Operações Oficiais de Crédito)" if cod.startswith("74") else "Orçamentária"


class Casador:
    """Associa uma UO (código + descrição do ano) a um fundo do cadastro."""

    def __init__(self, cadastro: list[dict]):
        self.regras = []
        for f in cadastro:
            padrao = f.get("padrao_uo") or ""
            sigla = norm(f.get("sigla"))
            self.regras.append({
                "id": f["id"],
                "re": re.compile(padrao) if padrao else None,
                "sigla": re.compile(rf"(?<![A-Z]){re.escape(sigla)}(?![A-Z])") if len(sigla) >= 3 and " " not in sigla else None,
                "uos": {u.strip().zfill(5) for u in (f.get("uo_referencia") or "").split("|") if u.strip()},
                "tem_uo": bool(padrao or f.get("uo_referencia")),
            })

    def casar(self, cod: str, desc: str, so_explicito: bool = False) -> str | None:
        """so_explicito=True (textos do MTO): só aceita o padrão de nome se o
        texto disser "FUNDO"; aceita sigla mesmo de fundo sem UO (Fundeb, FPE)."""
        d = norm(desc)
        for r in self.regras:          # 1) padrão de nome (sobrevive a troca de código)
            if r["re"] and r["re"].search(d) and (not so_explicito or "FUNDO" in d):
                return r["id"]
        for r in self.regras:          # 2) sigla citada na descrição ("Supervisão do FNO")
            if r["sigla"] and (r["tem_uo"] or so_explicito) and r["sigla"].search(d):
                return r["id"]
        if so_explicito:
            return None
        for r in self.regras:          # 3) código de UO de referência
            if cod in r["uos"]:
                return r["id"]
        return None


def carregar_execucao() -> tuple[list[dict], dict[int, str]]:
    linhas, origem = [], {}
    for arq in sorted(glob.glob(os.path.join(DADOS, "bruto", "siop_*.csv"))):
        ano = int(re.search(r"(\d{4})", os.path.basename(arq)).group(1))
        rs = ler_csv(arq)
        if not rs:
            continue
        origem[ano] = "SIOP via orcamentoBR"
        for r in rs:
            r["exercicio"] = ano
            r["uo_cod"] = r.get("uo_cod", "").zfill(5)
            linhas.append(r)
    for r in ler_csv(os.path.join(DADOS, "semente_bassi_2018.csv")):
        ano = int(r["exercicio"])
        if ano in origem and origem[ano].startswith("SIOP"):
            continue
        origem[ano] = "Bassi (2019), TD Ipea 2458, Tabela 3 — SIAFI/STN"
        r["exercicio"] = ano
        r["uo_cod"] = r["uo_cod"].zfill(5)
        linhas.append(r)
    return linhas, origem


def categoria_principal(classes: list[dict], natureza: str, no_orc: str) -> str:
    por_marco = {c["marco"]: c["classificacao"] for c in classes}
    for m in ("BASSI", "AC1494"):
        if m in por_marco and por_marco[m] in ("Contábil", "Financeiro", "Misto"):
            return por_marco[m]
    n = norm(natureza)
    if "PRIVADA" in n:
        return "Natureza privada"
    if "TRANSFERENCIA" in n:
        return "Transferência"
    if "AUTARQUIA" in n:
        return "Autarquia"
    return "Sem classificação"


def montar() -> dict:
    cadastro = ler_csv(os.path.join(DADOS, "fundos.csv"))
    classif = ler_csv(os.path.join(DADOS, "classificacoes.csv"))
    marcos = ler_csv(os.path.join(DADOS, "marcos.csv"))
    ids_marco = {m["id"] for m in marcos}
    casador = Casador(cadastro)

    por_fundo_class = defaultdict(list)
    for c in classif:
        if c["marco"] not in ids_marco:
            raise SystemExit(f"classificacoes.csv: marco desconhecido {c['marco']!r}")
        por_fundo_class[c["fundo"]].append({"marco": c["marco"], "classificacao": c["classificacao"],
                                            "detalhe": c.get("detalhe", ""), "ref": c.get("ref_et", "")})

    fundos: dict[str, dict] = {}
    for f in cadastro:
        fundos[f["id"]] = {
            "id": f["id"], "sigla": f["sigla"], "nome": f["nome"], "cadastrado": True,
            "natureza_juridica": f.get("natureza_juridica", ""), "no_orcamento": f.get("no_orcamento", ""),
            "fontes_referencia": [x for x in (f.get("fontes_referencia") or "").split("|") if x],
            "ug": f.get("ug", ""), "cnpj": f.get("cnpj", ""), "observacao": f.get("observacao", ""),
            "uo_referencia": [u.zfill(5) for u in (f.get("uo_referencia") or "").split("|") if u],
            "classificacoes": por_fundo_class.get(f["id"], []),
        }

    linhas, origem = carregar_execucao()
    exec_ = defaultdict(lambda: defaultdict(lambda: dict.fromkeys(METRICAS, 0.0)))
    presente = defaultdict(set)   # (fid, ano) -> métricas que a fonte do ano informa
    uos = defaultdict(lambda: defaultdict(dict))
    fontes = defaultdict(lambda: defaultdict(lambda: {"desc": "", "atual": 0.0, "emp": 0.0, "pago": 0.0}))
    rps = defaultdict(lambda: defaultdict(lambda: {"desc": "", "atual": 0.0, "emp": 0.0}))
    gnds = defaultdict(lambda: defaultdict(lambda: {"desc": "", "atual": 0.0, "emp": 0.0}))
    nao_casadas = 0

    for r in linhas:
        cod, desc, ano = r["uo_cod"], r.get("uo_desc", ""), r["exercicio"]
        if not eh_candidata(cod, desc):
            continue
        fid = casador.casar(cod, desc)
        if fid is None:
            nao_casadas += 1
            fid = f"UO-{cod}"
            if fid not in fundos:
                fundos[fid] = {"id": fid, "sigla": f"UO {cod}", "nome": desc, "cadastrado": False,
                               "natureza_juridica": "", "no_orcamento": "Sim", "fontes_referencia": [],
                               "ug": "", "cnpj": "", "observacao": "Detectado automaticamente no SIOP (UO de fundo sem cadastro).",
                               "uo_referencia": [], "classificacoes": []}
        e = exec_[fid][ano]
        for m in METRICAS:
            if r.get(m) not in (None, ""):
                e[m] += num(r.get(m))
                presente[(fid, ano)].add(m)
        uos[fid][ano][cod] = {"cod": cod, "desc": desc, "dimensao": dimensao_uo(cod),
                              "categoria_bassi": r.get("categoria_bassi", "")}
        a = num(r.get("loa_mais_credito")); em = num(r.get("empenhado")); pg = num(r.get("pago"))
        if r.get("fonte_cod"):
            fo = fontes[fid][(ano, r["fonte_cod"])]
            fo["desc"] = r.get("fonte_desc", ""); fo["atual"] += a; fo["emp"] += em; fo["pago"] += pg
        if r.get("rp_cod"):
            x = rps[fid][(ano, r["rp_cod"])]; x["desc"] = r.get("rp_desc", ""); x["atual"] += a; x["emp"] += em
        if r.get("gnd_cod"):
            x = gnds[fid][(ano, r["gnd_cod"])]; x["desc"] = r.get("gnd_desc", ""); x["atual"] += a; x["emp"] += em

    def por_ano(d):
        out = defaultdict(list)
        for (ano, cod), v in d.items():
            out[str(ano)].append({"cod": cod, **{k: (round(x, 2) if isinstance(x, float) else x) for k, x in v.items()}})
        for lst in out.values():
            lst.sort(key=lambda z: -z["atual"])
        return dict(out)

    # --- MTO 2026: códigos que se conectam a cada fundo --------------------
    for f in fundos.values():
        f["mto"] = {"uos": [], "fontes": [], "receitas": []}
    for u in ler_csv(os.path.join(DADOS, "mto2026_uos.csv")):
        if u.get("uo_de_fundo") != "sim":
            continue
        fid = u.get("fundo_id") or casador.casar(u["uo_cod"], u["descricao"]) or f"UO-{u['uo_cod']}"
        if fid in fundos:
            fundos[fid]["mto"]["uos"].append({"cod": u["uo_cod"], "desc": u["descricao"], "sigla": u.get("sigla", "")})
    mto_fontes = ler_csv(os.path.join(DADOS, "mto2026_fontes.csv"))
    info_fonte = {fo["fonte_cod"]: fo for fo in mto_fontes}
    for fo in mto_fontes:
        for fid in filter(None, fo.get("fundo_id", "").split("|")):
            if fid in fundos:
                fundos[fid]["mto"]["fontes"].append({"cod": fo["fonte_cod"], "desc": fo["descricao"],
                                                     "vinculo": fo["vinculo"], "justificativa": fo.get("justificativa", "")})
    mto_receitas = ler_csv(os.path.join(DADOS, "mto2026_receitas.csv"))
    for rc in mto_receitas:
        for fid in filter(None, rc.get("fundo_id", "").split("|")):
            if fid in fundos:
                fundos[fid]["mto"]["receitas"].append({"cod": rc["natureza_cod"], "desc": rc["descricao"]})

    # --- Verificação empírica: onde as fontes ligadas a fundos são executadas --
    verif: dict[str, dict] = {}
    exec_fonte = defaultdict(lambda: defaultdict(lambda: {"atual": 0.0, "emp": 0.0, "pago": 0.0, "dentro": 0.0}))
    for arq in sorted(glob.glob(os.path.join(DADOS, "bruto", "siop_fontes_*.csv"))):
        ano = re.search(r"(\d{4})", os.path.basename(arq)).group(1)
        for r in ler_csv(arq):
            spec = r["fonte_cod"][-3:]
            info = info_fonte.get(spec)
            if not info:
                continue
            ligados = [x for x in info.get("fundo_id", "").split("|") if x]
            uo = r["uo_cod"].zfill(5)
            fundo_uo = (casador.casar(uo, r.get("uo_desc", "")) or "") if eh_candidata(uo, r.get("uo_desc", "")) else ""
            a, em, pg = num(r.get("loa_mais_credito")), num(r.get("empenhado")), num(r.get("pago"))
            v = verif.setdefault(spec, {"cod": spec, "desc": info["descricao"], "fundos": ligados,
                                        "vinculo": info["vinculo"], "justificativa": info.get("justificativa", ""), "anos": {}})
            va = v["anos"].setdefault(ano, {"atual": 0.0, "emp": 0.0, "dentro": 0.0, "uos": []})
            dentro = fundo_uo in ligados
            va["atual"] += a; va["emp"] += em; va["dentro"] += a if dentro else 0.0
            va["uos"].append({"uo": uo, "desc": r.get("uo_desc", ""), "fundo_uo": fundo_uo, "fonte": r["fonte_cod"],
                              "atual": round(a, 2), "emp": round(em, 2), "pago": round(pg, 2)})
            for fid in ligados:
                x = exec_fonte[fid][ano]
                x["atual"] += a; x["emp"] += em; x["pago"] += pg; x["dentro"] += a if dentro else 0.0
    for v in verif.values():
        for va in v["anos"].values():
            va["uos"].sort(key=lambda z: -z["atual"])
            t = va["atual"]
            share = va["dentro"] / t if t else 0
            va["status"] = ("sem execução" if t == 0 else "confirmado" if share >= 0.5
                            else "parcial" if share > 0 else "fora das UOs do fundo")
            va["dentro_pct"] = round(share * 100, 1)
            for k in ("atual", "emp", "dentro"):
                va[k] = round(va[k], 2)

    saida = []
    for fid, f in fundos.items():
        f["exec_fonte"] = {a: {k: round(x, 2) for k, x in v.items()} for a, v in sorted(exec_fonte[fid].items())}
        f["exec"] = {str(a): {CURTO[m]: (round(v, 2) if m in presente[(fid, a)] else None) for m, v in e.items()}
                     for a, e in sorted(exec_[fid].items())}
        f["uos"] = {str(a): sorted(v.values(), key=lambda z: z["cod"]) for a, v in sorted(uos[fid].items())}
        f["fontes"] = por_ano(fontes[fid])
        f["rp"] = por_ano(rps[fid])
        f["gnd"] = por_ano(gnds[fid])
        f["categoria"] = categoria_principal(f["classificacoes"], f["natureza_juridica"], f["no_orcamento"])
        # histórico de códigos de UO: quando o mesmo fundo aparece com UOs diferentes
        hist, anterior = [], None
        for a in sorted(uos[fid]):
            cods = sorted(uos[fid][a])
            if cods != anterior:
                hist.append({"desde": a, "uos": cods})
                anterior = cods
        f["historico_uo"] = hist
        saida.append(f)

    anos = sorted(origem)
    saida.sort(key=lambda f: (-(f["exec"].get(str(anos[-1]), {}).get("atual", 0) if anos else 0), f["sigla"]))
    return {
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "anos": anos,
        "origem_por_ano": {str(a): o for a, o in origem.items()},
        "somente_semente": all(not o.startswith("SIOP") for o in origem.values()),
        "uos_sem_cadastro": nao_casadas,
        "marcos": marcos,
        "fundos": saida,
        "mto": {
            "fontes": mto_fontes,
            "receitas": mto_receitas,
            "uos_de_fundo": [u for u in ler_csv(os.path.join(DADOS, "mto2026_uos.csv")) if u.get("uo_de_fundo") == "sim"],
        },
        "verificacao_fontes": sorted(verif.values(), key=lambda v: v["cod"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="site/dados.json")
    a = ap.parse_args()
    payload = montar()
    os.makedirs(os.path.dirname(a.saida) or ".", exist_ok=True)
    tmp = a.saida + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.saida)
    n_exec = sum(1 for f in payload["fundos"] if f["exec"])
    print(f"{len(payload['fundos'])} fundos ({n_exec} com execução), anos {payload['anos']}, "
          f"{os.path.getsize(a.saida)/1024:.0f} KB -> {a.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
