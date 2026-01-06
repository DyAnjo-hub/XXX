# -*- coding: utf-8 -*-
"""
MEGA winrate model (shrinkage) — versão robusta p/ Streamlit

Fixes importantes (para não "matar" pp por bug):
1) Normaliza nomes de campeões (igual filosofia do seu modelo antigo):
   - lowercase
   - remove espaços e apóstrofos
   Ex.: "K'Sante" -> "ksante", "Xin Zhao" -> "xinzhao"

2) Agrega amostra por par SOMANDO todas as roles.
   Sua planilha tem múltiplas linhas por (Campeao, Champion) com Role diferente.
   Se você pegar só a primeira linha, você perde amostra e o shrink fica parecendo "forte demais".

3) Lookup rápido via dicionários (bem mais rápido no Streamlit Cloud).

Base esperada no .xlsx:
- abas: Winrate_vs e Winrate_with
- colunas (aceita variações de maiúsculas): Campeao, Champion, Games, Winrate
"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from typing import Dict, Optional, Tuple, Union, Any, List

import pandas as pd

# ================================
# Parâmetros (você pode ajustar)
# ================================

MU_GLOBAL = 0.50     # baseline (50%)
K_PRIOR = 30.0       # força do prior (quanto maior, mais puxa pro 50)
WEIGHT_CAP = 50.0    # teto do peso ~sqrt(games)

DEFAULT_XLSX = "dados_mega_merged.xlsx"

# ================================
# Estado (stats agregados)
# ================================

_vs_stats: Optional[Dict[Tuple[str, str], Tuple[float, float]]] = None   # (a,b) -> (wins, games)
_with_stats: Optional[Dict[Tuple[str, str], Tuple[float, float]]] = None # (a,b) -> (wins, games)


# ================================
# Normalização
# ================================

def norm_name(x: Any) -> Optional[str]:
    if x is None or pd.isna(x):
        return None
    s = str(x).strip().lower()
    if not s:
        return None
    s = s.replace(" ", "").replace("'", "").replace(".", "")
    return s


def _norm_colname(c: str) -> str:
    c = str(c).strip().lower().replace(" ", "_").replace("-", "_")
    return c


def _pick(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for cand in candidates:
        if cand in df.columns:
            return cand
    return None


def _load_sheet(excel: Union[str, os.PathLike, object], sheet: str) -> pd.DataFrame:
    df = pd.read_excel(excel, sheet_name=sheet)
    df.columns = [_norm_colname(c) for c in df.columns]
    return df


def init_from_excel(excel: Union[str, os.PathLike, object]) -> None:
    """
    Carrega e pré-processa:
    - normaliza colunas
    - agrega por par (somando roles)
    - cria dicts de lookup
    """
    global _vs_stats, _with_stats

    vs = _load_sheet(excel, "Winrate_vs")
    wt = _load_sheet(excel, "Winrate_with")

    # mapeia colunas mínimas
    col_a_vs = _pick(vs, ["campeao", "champion_a", "champion1", "champion_1", "champion"])
    col_b_vs = _pick(vs, ["vs", "opponent", "enemy", "champion_b", "champion2", "champion_2", "champion"])
    col_g_vs = _pick(vs, ["games", "matches", "n", "count"])
    col_wr_vs = _pick(vs, ["winrate", "wr", "win_rate"])

    # seu formato: campeao + champion (col_b_vs vai cair em champion também; então força campeao/champion)
    if "campeao" in vs.columns and "champion" in vs.columns:
        col_a_vs = "campeao"
        col_b_vs = "champion"

    missing_vs = [("campeao/champion", col_a_vs), ("vs/champion", col_b_vs), ("games", col_g_vs), ("winrate", col_wr_vs)]
    if any(v is None for _, v in missing_vs):
        raise KeyError(f"Winrate_vs: colunas insuficientes. Encontradas: {list(vs.columns)}")

    col_a_w = _pick(wt, ["campeao", "champion_a", "champion1", "champion_1", "champion"])
    col_b_w = _pick(wt, ["with", "ally", "pair", "champion_b", "champion2", "champion_2", "champion"])
    col_g_w = _pick(wt, ["games", "matches", "n", "count"])
    col_wr_w = _pick(wt, ["winrate", "wr", "win_rate"])

    if "campeao" in wt.columns and "champion" in wt.columns:
        col_a_w = "campeao"
        col_b_w = "champion"

    missing_w = [("campeao/champion", col_a_w), ("with/champion", col_b_w), ("games", col_g_w), ("winrate", col_wr_w)]
    if any(v is None for _, v in missing_w):
        raise KeyError(f"Winrate_with: colunas insuficientes. Encontradas: {list(wt.columns)}")

    # agrega por par
    def build_stats(df: pd.DataFrame, col_a: str, col_b: str, col_games: str, col_wr: str) -> Dict[Tuple[str, str], Tuple[float, float]]:
        tmp = defaultdict(lambda: [0.0, 0.0])  # wins, games
        for _, r in df.iterrows():
            a = norm_name(r[col_a])
            b = norm_name(r[col_b])
            if not a or not b:
                continue
            g = float(r[col_games])
            wr = float(r[col_wr])
            wins = wr * g
            tmp[(a, b)][0] += wins
            tmp[(a, b)][1] += g
        return {k: (v[0], v[1]) for k, v in tmp.items()}

    _vs_stats = build_stats(vs, col_a_vs, col_b_vs, col_g_vs, col_wr_vs)
    _with_stats = build_stats(wt, col_a_w, col_b_w, col_g_w, col_wr_w)


def _ensure_loaded() -> None:
    global _vs_stats, _with_stats
    if _vs_stats is not None and _with_stats is not None:
        return
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, DEFAULT_XLSX)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Não achei '{DEFAULT_XLSX}' em: {path}\n"
            "Suba o arquivo no repo OU use o uploader do Streamlit."
        )
    init_from_excel(path)


# ================================
# Shrink + peso
# ================================

def shrink_prob(wins: float, games: float, mu: float = MU_GLOBAL, k: float = K_PRIOR) -> float:
    games = max(float(games), 0.0)
    wins = max(float(wins), 0.0)
    return (wins + k * mu) / (games + k)


def weight_from_games(games: float) -> float:
    g = max(float(games), 0.0)
    return min(math.sqrt(g), WEIGHT_CAP)


# ================================
# Cálculo (VS / WITH)
# ================================

def calcular_winrate_vs(time_a, time_b) -> float:
    """Retorna fração (0–1)."""
    _ensure_loaded()
    assert _vs_stats is not None

    A = [norm_name(c) for c in time_a]
    B = [norm_name(c) for c in time_b]

    total = 0.0
    wtot = 0.0
    for a in A:
        if not a:
            continue
        for b in B:
            if not b:
                continue
            key = (a, b)
            if key not in _vs_stats:
                continue
            wins, games = _vs_stats[key]
            p = shrink_prob(wins, games)
            w = weight_from_games(games)
            total += p * w
            wtot += w

    return MU_GLOBAL if wtot <= 0 else (total / wtot)


def calcular_winrate_with(time) -> float:
    """Retorna fração (0–1)."""
    _ensure_loaded()
    assert _with_stats is not None

    champs = [norm_name(c) for c in time]

    total = 0.0
    wtot = 0.0
    for i in range(len(champs)):
        a = champs[i]
        if not a:
            continue
        for j in range(i + 1, len(champs)):
            b = champs[j]
            if not b:
                continue
            key = (a, b)
            if key not in _with_stats:
                key = (b, a)
                if key not in _with_stats:
                    continue
            wins, games = _with_stats[key]
            p = shrink_prob(wins, games)
            w = weight_from_games(games)
            total += p * w
            wtot += w

    return MU_GLOBAL if wtot <= 0 else (total / wtot)


def calcular_chance_vitoria(time_azul, time_vermelho, verbose: bool = False):
    """
    Retorna (p_azul, p_vermelho) em %.
    Nota: isso é score normalizado (não é prob calibrada).
    """
    azul_vs = calcular_winrate_vs(time_azul, time_vermelho)
    ver_vs = calcular_winrate_vs(time_vermelho, time_azul)

    azul_w = calcular_winrate_with(time_azul)
    ver_w = calcular_winrate_with(time_vermelho)

    score_azul = (azul_vs + azul_w) / 2.0
    score_ver = (ver_vs + ver_w) / 2.0

    soma = score_azul + score_ver
    if soma <= 0:
        return 50.0, 50.0

    p_azul = (score_azul / soma) * 100.0
    p_ver = (score_ver / soma) * 100.0

    if verbose:
        print(f"azul_vs={azul_vs:.4f} azul_with={azul_w:.4f} score_azul={score_azul:.4f}")
        print(f"ver_vs={ver_vs:.4f} ver_with={ver_w:.4f} score_ver={score_ver:.4f}")
        print(f"p_azul={p_azul:.2f} p_ver={p_ver:.2f}")

    return p_azul, p_ver


def diagnostico_draft(time_azul, time_vermelho):
    """
    Te diz se o modelo está "cego" (pouca cobertura) naquele draft.
    Retorna:
      - vs_pairs_found / 25
      - with_pairs_found / 10
      - avg_games_vs, avg_games_with
    """
    _ensure_loaded()
    assert _vs_stats is not None and _with_stats is not None

    A = [norm_name(c) for c in time_azul]
    B = [norm_name(c) for c in time_vermelho]

    found_vs = 0
    games_vs = []

    for a in A:
        for b in B:
            key=(a,b)
            if key in _vs_stats:
                found_vs += 1
                games_vs.append(_vs_stats[key][1])

    champs=A
    found_with=0
    games_with=[]
    for i in range(len(champs)):
        for j in range(i+1,len(champs)):
            a=champs[i]; b=champs[j]
            key=(a,b)
            if key not in _with_stats:
                key=(b,a)
            if key in _with_stats:
                found_with += 1
                games_with.append(_with_stats[key][1])

    def avg(x): return float(sum(x)/len(x)) if x else 0.0

    return {
        "vs_pairs_found": found_vs,
        "vs_pairs_total": 25,
        "with_pairs_found": found_with,
        "with_pairs_total": 10,
        "avg_games_vs": avg(games_vs),
        "avg_games_with": avg(games_with),
    }
