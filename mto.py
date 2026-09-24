#!/usr/bin/env python3
"""
mto.py — extrai do MTO 2026 (Manual Técnico de Orçamento, SOF/MPO) os códigos que
se conectam a fundos públicos, para estudo e verificação.

Entrada: texto do MTO (pdftotext -layout não é necessário; texto corrido basta).
Saídas (dados/):
  mto2026_uos.csv        classificação institucional (12.2.1) — todas as UOs, com
                         marcação das UOs de fundo (xx9xx, "Fundo" ou "Recursos sob
                         Supervisão do Fundo")
  mto2026_fontes.csv     fontes/destinações (12.1.4.2) ligadas a fundos, com o tipo
                         de vínculo: "explícito" (o fundo é nomeado na descrição da
                         fonte) ou "a verificar" (vinculação temática, hipótese a
                         confirmar com a execução — o painel cruza com o SIOP)
  mto2026_receitas.csv   naturezas de receita (12.1) cuja descrição cita fundo

Uso: python3 mto.py caminho/mto2026.txt
"""
from __future__ import annotations

import csv
import re
import sys
import unicodedata

sys.path.insert(0, ".")
from montar import Casador, ler_csv, norm  # noqa: E402

LIXO = re.compile(r"^(Manual Técnico de Orçamento.*|20\d\d|\d{3}|Código Descrição Sigla|CÓDIGO .*DESCRIÇÃO)$")


def linhas_limpas(txt: list[str]) -> list[str]:
    return [l.rstrip() for l in txt if l.strip() and not LIXO.match(l.strip())]


def secao(todas: list[str], inicio: str, fim: str) -> list[str]:
    i = next(k for k, l in enumerate(todas) if l.strip().startswith(inicio) and k > 1000)
    j = next(k for k, l in enumerate(todas) if l.strip().startswith(fim) and k > i)
    return todas[i + 1:j]


def juntar(linhas: list[str], cod_re: re.Pattern) -> list[tuple[str, str]]:
    itens, atual = [], None
    for l in linhas:
        m = cod_re.match(l.strip())
        if m:
            if atual:
                itens.append(atual)
            atual = [m.group(1), m.group(2).strip()]
        elif atual and not re.match(r"^(I|II|III|IV) - |^\(\d\)|^12\.", l.strip()):
            atual[1] += " " + l.strip()
    if atual:
        itens.append(atual)
    return [(c, re.sub(r"\s+", " ", d).strip()) for c, d in itens]


SIGLA = re.compile(r"\s+((?:[A-Z][A-Za-z0-9/ªº-]*){1}|-)$")


def separa_sigla(desc: str) -> tuple[str, str]:
    """A tabela traz 'Descrição Sigla' na mesma linha; a sigla é o último token
    quando tem ao menos duas maiúsculas (FNS, FAer, FUNCAFÉ) ou é '-'."""
    partes = desc.rsplit(" ", 1)
    if len(partes) == 2:
        cand = partes[1]
        maius = sum(1 for c in cand if c.isupper())
        if cand == "-" or (maius >= 2 and len(cand) <= 12 and not cand.endswith(")")):
            return partes[0].rstrip(" -"), "" if cand == "-" else cand
    return desc, ""


def eh_uo_fundo(cod: str, desc: str) -> bool:
    return (cod[2] == "9") or "FUNDO" in norm(desc)


# Vínculos temáticos (hipóteses): fonte cuja destinação legal costuma alimentar um
# fundo sem nomeá-lo. Servem para verificação contra a execução observada.
A_VERIFICAR = {
    "007": ("FUNSET", "Prevenção de acidentes de trânsito — destinação típica do Funset"),
    "020": ("FUNSET", "Sinalização, fiscalização e educação de trânsito"),
    "144": ("FUNSET", "Sinalização, fiscalização e educação de trânsito"),
    "040": ("FAT", "Seguro-desemprego e abono salarial — despesas típicas do FAT"),
    "054": ("FRGPS", "Benefícios do RGPS"),
    "064": ("FNAC", "Fomento da aviação civil e infraestrutura aeronáutica"),
    "083": ("FDD", "Reparação de danos a interesses difusos e coletivos"),
    "069": ("FNMA", "Multas ambientais revertidas a fundos (Lei 9.605/1998)"),
    "072": ("FNMC", "Mitigação e adaptação à mudança do clima (parcela do petróleo)"),
    "091": ("FMM", "Apoio à Marinha Mercante e à construção naval"),
    "115": ("FMM", "Construção e reparo de embarcações em estaleiros brasileiros"),
    "207": ("FNO", "Transferência constitucional — financiamento ao setor produtivo do Norte"),
    "208": ("FCO", "Transferência constitucional — financiamento ao setor produtivo do Centro-Oeste"),
    "209": ("FNE", "Transferência constitucional — financiamento ao setor produtivo do Nordeste"),
    "210": ("FNE", "Transferência constitucional — Nordeste/Semiárido"),
    "025": ("FNA", "Repressão ao tráfico ilícito de drogas"),
    "079": ("FNCA", "Proteção a crianças e adolescentes ameaçados de morte"),
    "028": ("FNDCT", "Estudos de geologia e geofísica — CT-Petro/CT-Mineral"),
    "114": ("FNDCT", "P&D de interesse do desenvolvimento regional (CT)"),
}
GRUPO = {
    "082": ("FDA|FDNE|FDCO", "explícito", "Fonte cita os Fundos de Desenvolvimento Regionais"),
    "069": ("FNMA", "a verificar", "Multas ambientais revertidas a fundos (sem nomear); o FNMA é o destino típico"),
}
# Fundos setoriais de C&T (CT-*) integram o FNDCT.
CT_FNDCT = re.compile(r"^CT-|\bCT-")


def vincular_fonte(cod: str, desc: str, casador: Casador) -> tuple[str, str, str] | None:
    d = norm(desc)
    if CT_FNDCT.search(desc):
        return "FNDCT", "explícito", "Fundo setorial de C&T (CT-*), que integra o FNDCT"
    if "FISTEL" in d:
        alvo = "FUST" if "FUST" in d else "FISTEL"
        if re.search(r"\bFSA\b", d):
            return "FNC", "explícito", "Recursos do Fistel destinados ao FSA (categoria de programação do FNC)"
        return alvo, "explícito", "Fonte nomeia o Fistel" + (" e o Fust" if alvo == "FUST" else "")
    if "FUNDO SOCIAL" in d or re.search(r"\bFS\b", d):
        return "FSOCIAL", "explícito", "Fonte nomeia o Fundo Social"
    if "FUNDO DE PARTICIPACAO DOS MUNICIPIOS" in d:
        return "FPM", "explícito", "Transferência constitucional do FPM"
    if "FUNDO DE PARTICIPACAO DOS ESTADOS" in d:
        return "FPE", "explícito", "Transferência constitucional do FPE"
    if "FG-FIES" in d or "FINANCIAMENTO ESTUDANTIL" in d:
        return "FIES", "explícito", "Fundo Garantidor do FIES"
    if re.search(r"\bFAT\b", d):
        return "FAT", "explícito", "Fonte nomeia o FAT"
    if re.search(r"\bFCDF\b", d):
        return "FCDF", "explícito", "Fonte nomeia o FCDF"
    if re.search(r"\bFSA\b", d) or "AUDIOVISUAL" in d:
        return "FNC", "explícito", "Fundo Setorial do Audiovisual (categoria de programação do FNC)"
    if cod in GRUPO:
        return GRUPO[cod]
    fid = casador.casar("00000", desc, so_explicito=True)
    if fid:
        return fid, "explícito", "Fonte nomeia o fundo"
    if re.search(r"\bFUNDOS?\b|\bFUNAPOL\b|\bFUNDAF\b|\bFUNCAP\b", d):
        return "", "explícito (fundo sem cadastro)", "Fonte cita fundo que não está no cadastro do painel"
    if cod in A_VERIFICAR:
        fid, porque = A_VERIFICAR[cod]
        return fid, "a verificar", porque
    return None


def main(caminho: str) -> int:
    todas = open(caminho, encoding="utf-8").read().splitlines()
    cadastro = ler_csv("dados/fundos.csv")
    casador = Casador(cadastro)

    # --- UOs (12.2.1) --------------------------------------------------------
    bloco = linhas_limpas(secao(todas, "12.2.1 CLASSIFICAÇÃO INSTITUCIONAL", "12.2.2 CLASSIFICAÇÃO FUNCIONAL"))
    uos = juntar(bloco, re.compile(r"^(\d{5}) (.*)$"))
    with open("dados/mto2026_uos.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["uo_cod", "descricao", "sigla", "uo_de_fundo", "fundo_id"])
        n_f = 0
        for cod, desc in uos:
            desc, sig = separa_sigla(desc)
            fundo = eh_uo_fundo(cod, desc)
            fid = casador.casar(cod, desc) if fundo else ""
            n_f += fundo
            w.writerow([cod, desc, sig, "sim" if fundo else "não", fid or ""])
    print(f"UOs: {len(uos)} ({n_f} de fundo)")

    # --- Fontes (12.1.4.2) ---------------------------------------------------
    bloco = linhas_limpas(secao(todas, "12.1.4.2. Fontes/Destinações de Recursos", "12.2. TABELAS - DESPESA"))
    fontes = juntar(bloco, re.compile(r"^(\d{3}) (.+)$"))
    n = 0
    with open("dados/mto2026_fontes.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["fonte_cod", "descricao", "fundo_id", "vinculo", "justificativa"])
        for cod, desc in fontes:
            v = vincular_fonte(cod, desc, casador)
            if v:
                n += 1
                w.writerow([cod, desc, *v])
    print(f"Fontes: {len(fontes)} ({n} ligadas a fundos)")

    # --- Naturezas de receita (12.1) ------------------------------------------
    bloco = linhas_limpas(secao(todas, "12.1. TABELAS – RECEITA", "12.1.4.1. Grupos de fontes"))
    bloco = [p for l in bloco for p in re.split(r"\s(?=\d\.\d\.\d\.\d\.\d\d\.\d\.\d(?:\s|$))", l)]
    recs = juntar(bloco, re.compile(r"^(\d\.\d\.\d\.\d\.\d\d\.\d\.\d)\s*(.*)$"))
    vistos, n = set(), 0
    with open("dados/mto2026_receitas.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["natureza_cod", "descricao", "fundo_id"])
        for cod, desc in recs:
            if cod in vistos or "FUNDO" not in norm(desc):
                continue
            vistos.add(cod)
            fid = casador.casar("00000", desc, so_explicito=True) or ""
            if not fid:
                v = vincular_fonte("", desc, casador)
                fid = v[0] if v else ""
            w.writerow([cod, desc, fid])
            n += 1
    print(f"Naturezas de receita que citam fundo: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
