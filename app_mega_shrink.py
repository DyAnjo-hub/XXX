# -*- coding: utf-8 -*-
"""
MEGA winrate model (com shrinkage)

Diferenças vs versão antiga:
- Aplica shrinkage Bayesiano simples por par (wins/games) para reduzir ruído de amostra pequena
- Usa pesos ~sqrt(games) (com teto) para evitar que poucos pares gigantes dominem tudo
- Carregamento flexível da base:
  - por padrão, tenta abrir "dados_mega_merged.xlsx" na mesma pasta deste arquivo
  - no Streamlit, você pode chamar init_from_excel(file_like) usando um uploader
"""

from __future__ import annotations

import math
import os
from typing import Optional, Union

import pandas as pd

# ================================
# Estado (dataframes carregados)
# ================================

_winrate_vs: Optional[pd.DataFrame] = None
_winrate_with: Optional[pd.DataFrame] = None

# ================================
# Parâmetros de estabilidade (shrinkage)
# ================================

MU_GLOBAL = 0.50   # baseline (50%)
K_PRIOR = 30.0     # força do prior (em "jogos virtuais") — ajuste se quiser

# Peso por par (para média agregada)
WEIGHT_CAP = 50.0  # teto do peso (evita dominância absoluta)

# Nome padrão do arquivo
DEFAULT_XLSX = "dados_mega_merged.xlsx"



# ================================
# Normalização de colunas (robusto)
# ================================

def _norm_colname(c: str) -> str:
    c = str(c).strip().lower()
    c = c.replace(" ", "_")
    c = c.replace("-", "_")
    return c

def _rename_columns_vs(df: pd.DataFrame) -> pd.DataFrame:
    """Garante colunas: champion, vs, winrate, games"""
    df = df.copy()
    df.columns = [_norm_colname(c) for c in df.columns]

    def pick(candidates):
        for cand in candidates:
            if cand in df.columns:
                return cand
        return None

    col_champion = pick(["champion", "champ", "champion_name", "champ_name", "champs", "character", "hero"])
    col_vs = pick(["vs", "versus", "opponent", "against", "enemy", "target"])
    col_wr = pick(["winrate", "win_rate", "wr", "winrate_pct", "winrate_percent", "win%"])
    col_games = pick(["games", "game", "matches", "match", "n_games", "total_games", "total_matches", "sample", "samplesize"])

    mapping = {}
    if col_champion and col_champion != "champion":
        mapping[col_champion] = "champion"
    if col_vs and col_vs != "vs":
        mapping[col_vs] = "vs"
    if col_wr and col_wr != "winrate":
        mapping[col_wr] = "winrate"
    if col_games and col_games != "games":
        mapping[col_games] = "games"

    df = df.rename(columns=mapping)

    missing = [c for c in ["champion", "vs", "winrate", "games"] if c not in df.columns]
    if missing:
        raise KeyError(f"Colunas faltando na aba Winrate_vs: {missing}. Colunas encontradas: {list(df.columns)}")
    return df

def _rename_columns_with(df: pd.DataFrame) -> pd.DataFrame:
    """Garante colunas: champion, with, winrate, games"""
    df = df.copy()
    df.columns = [_norm_colname(c) for c in df.columns]

    def pick(candidates):
        for cand in candidates:
            if cand in df.columns:
                return cand
        return None

    col_champion = pick(["champion", "champ", "champion_name", "champ_name", "champs", "character", "hero"])
    col_with = pick(["with", "ally", "pair", "together", "synergy_with", "with_champion"])
    col_wr = pick(["winrate", "win_rate", "wr", "winrate_pct", "winrate_percent", "win%"])
    col_games = pick(["games", "game", "matches", "match", "n_games", "total_games", "total_matches", "sample", "samplesize"])

    mapping = {}
    if col_champion and col_champion != "champion":
        mapping[col_champion] = "champion"
    if col_with and col_with != "with":
        mapping[col_with] = "with"
    if col_wr and col_wr != "winrate":
        mapping[col_wr] = "winrate"
    if col_games and col_games != "games":
        mapping[col_games] = "games"

    df = df.rename(columns=mapping)

    missing = [c for c in ["champion", "with", "winrate", "games"] if c not in df.columns]
    if missing:
        raise KeyError(f"Colunas faltando na aba Winrate_with: {missing}. Colunas encontradas: {list(df.columns)}")
    return df


def init_from_excel(excel: Union[str, os.PathLike, "pd.ExcelFile", object]) -> None:
    """
    Carrega as abas Winrate_vs e Winrate_with a partir de:
    - caminho (str/path)
    - file-like (ex.: UploadedFile do Streamlit)
    """
    global _winrate_vs, _winrate_with
    _winrate_vs = _rename_columns_vs(pd.read_excel(excel, sheet_name="Winrate_vs"))
    _winrate_with = _rename_columns_with(pd.read_excel(excel, sheet_name="Winrate_with"))


def _ensure_loaded() -> None:
    """Carrega a base padrão se ainda não tiver sido carregada."""
    global _winrate_vs, _winrate_with
    if _winrate_vs is not None and _winrate_with is not None:
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, DEFAULT_XLSX)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Não achei '{DEFAULT_XLSX}' em: {path}\n"
            f"- Coloque o arquivo nessa mesma pasta, ou\n"
            f"- No Streamlit, use o uploader e chame init_from_excel()."
        )
    init_from_excel(path)


# ================================
# Helpers
# ================================

def limpar_numero(x) -> float:
    """
    Converte números da planilha para float.
    Aceita:
    - 0.44
    - '0.44'
    - '8,886.00'
    - '55%'
    - 55  (interpreta como 55%)
    """
    if pd.isna(x):
        return 0.0
    if isinstance(x, (int, float)):
        v = float(x)
        # se veio como 55 em vez de 0.55, converte pra fração
        return v / 100.0 if v > 1.0 else v

    s = str(x).strip()
    if not s:
        return 0.0

    # remove separadores comuns
    s = s.replace(" ", "")
    s = s.replace("%", "")
    # cuidado: alguns exports usam vírgula como milhar
    # estratégia: remove vírgulas e depois tenta float; se falhar, troca vírgula por ponto
    try:
        v = float(s.replace(",", ""))
        return v / 100.0 if v > 1.0 else v
    except Exception:
        try:
            v = float(s.replace(".", "").replace(",", "."))
            return v / 100.0 if v > 1.0 else v
        except Exception:
            return 0.0


def normalizar_nome(nome) -> Optional[str]:
    """Normaliza nome de campeão (string) para bater com a planilha."""
    if pd.isna(nome):
        return None
    s = str(nome).strip()
    return s if s else None


def shrink_prob(wins: float, games: float, mu: float = MU_GLOBAL, k: float = K_PRIOR) -> float:
    """p_hat = (wins + k*mu) / (games + k)"""
    games = max(float(games), 0.0)
    wins = max(float(wins), 0.0)
    return (wins + k * mu) / (games + k)


def weight_from_games(games: float) -> float:
    """Peso saturado ~sqrt(games), com teto."""
    g = max(float(games), 0.0)
    w = math.sqrt(g)
    return min(w, WEIGHT_CAP)


# ================================
# Métricas VS e WITH (com shrink)
# ================================

def calcular_winrate_vs(time_a, time_b) -> float:
    """
    Winrate do time_a contra time_b, agregado sobre pares (A vs B).
    Retorna em % (0–100).
    """
    _ensure_loaded()
    assert _winrate_vs is not None

    # normaliza
    A = [normalizar_nome(c) for c in time_a]
    B = [normalizar_nome(c) for c in time_b]

    total_w = 0.0
    total_weight = 0.0

    for a in A:
        if not a:
            continue
        for b in B:
            if not b:
                continue

            row = _winrate_vs[(_winrate_vs["champion"] == a) & (_winrate_vs["vs"] == b)]
            if row.empty:
                continue

            # alguns arquivos têm colunas como strings
            wr = limpar_numero(row.iloc[0]["winrate"])   # fração
            games = limpar_numero(row.iloc[0]["games"])  # pode vir gigante

            wins = wr * games
            p_hat = shrink_prob(wins=wins, games=games)

            w = weight_from_games(games)
            total_w += p_hat * w
            total_weight += w

    if total_weight <= 0:
        return MU_GLOBAL * 100.0

    return (total_w / total_weight) * 100.0


def calcular_winrate_with(time) -> float:
    """
    Sinergia WITH do time, agregado sobre pares (A with B).
    Retorna em % (0–100).
    """
    _ensure_loaded()
    assert _winrate_with is not None

    champs = [normalizar_nome(c) for c in time]

    total_w = 0.0
    total_weight = 0.0

    # pares não ordenados (i < j)
    for i in range(len(champs)):
        a = champs[i]
        if not a:
            continue
        for j in range(i + 1, len(champs)):
            b = champs[j]
            if not b:
                continue

            # tenta A with B; se não achar, tenta B with A
            row = _winrate_with[(_winrate_with["champion"] == a) & (_winrate_with["with"] == b)]
            if row.empty:
                row = _winrate_with[(_winrate_with["champion"] == b) & (_winrate_with["with"] == a)]
            if row.empty:
                continue

            wr = limpar_numero(row.iloc[0]["winrate"])
            games = limpar_numero(row.iloc[0]["games"])

            wins = wr * games
            p_hat = shrink_prob(wins=wins, games=games)

            w = weight_from_games(games)
            total_w += p_hat * w
            total_weight += w

    if total_weight <= 0:
        return MU_GLOBAL * 100.0

    return (total_w / total_weight) * 100.0


def calcular_chance_vitoria(time_azul, time_vermelho, verbose: bool = False):
    """
    Retorna (chance_azul, chance_vermelho) em %.

    Nota: isso é um score normalizado (não prob calibrada).
    """
    azul_vs = calcular_winrate_vs(time_azul, time_vermelho)
    vermelho_vs = calcular_winrate_vs(time_vermelho, time_azul)

    azul_with = calcular_winrate_with(time_azul)
    vermelho_with = calcular_winrate_with(time_vermelho)

    score_azul = (azul_vs + azul_with) / 2.0
    score_vermelho = (vermelho_vs + vermelho_with) / 2.0

    soma = score_azul + score_vermelho
    if soma <= 0:
        return 50.0, 50.0

    chance_azul = (score_azul / soma) * 100.0
    chance_vermelho = (score_vermelho / soma) * 100.0

    if verbose:
        print(f"[DEBUG] azul_vs={azul_vs:.2f} azul_with={azul_with:.2f} score_azul={score_azul:.2f}")
        print(f"[DEBUG] ver_vs={vermelho_vs:.2f} ver_with={vermelho_with:.2f} score_ver={score_vermelho:.2f}")
        print(f"[DEBUG] chance azul={chance_azul:.2f} vermelho={chance_vermelho:.2f}")

    return chance_azul, chance_vermelho
