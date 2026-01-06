# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Optional, Tuple

import streamlit as st
import modelo_winrate_mega_shrink_warn as mega

# ===== Regras de entrada =====
RULE_A_ODD_MIN = 2.00
RULE_A_PP_MIN = 2.0
RULE_B_ODD_MIN = 1.70
RULE_B_PP_MIN = 3.0

def parse_float(s: str) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None

def parse_champs(raw: str) -> List[str]:
    return [c.strip() for c in raw.split(",") if c.strip()]

def implied_prob_pct(odd: float) -> Optional[float]:
    if odd is None or odd <= 1.0:
        return None
    return 100.0 / odd

def pick_side(p_azul: float, p_vermelho: float) -> str:
    return "AZUL" if p_azul >= p_vermelho else "VERMELHO"

def get_odd_for_side(side: str, odd_azul: float, odd_vermelho: float) -> float:
    return odd_azul if side == "AZUL" else odd_vermelho

def should_bet(odd: float, gap_pp: float) -> Tuple[bool, str]:
    if odd is None or odd <= 1.0:
        return False, "Odd inválida"
    if odd >= RULE_A_ODD_MIN and gap_pp >= RULE_A_PP_MIN:
        return True, f"Regra A: odd ≥ {RULE_A_ODD_MIN:.2f} e pp ≥ {RULE_A_PP_MIN:.1f}"
    if odd >= RULE_B_ODD_MIN and gap_pp >= RULE_B_PP_MIN:
        return True, f"Regra B: odd ≥ {RULE_B_ODD_MIN:.2f} e pp ≥ {RULE_B_PP_MIN:.1f}"
    return False, "Não bate as regras"

st.set_page_config(page_title="MEGA LoL – Decisor", layout="centered")
st.title("MEGA LoL – Decisor (draft + odds)")
st.caption(
    f"Entrada: (A) odd ≥ {RULE_A_ODD_MIN:.2f} e pp ≥ {RULE_A_PP_MIN:.1f} "
    f"OU (B) odd ≥ {RULE_B_ODD_MIN:.2f} e pp ≥ {RULE_B_PP_MIN:.1f}. "
    "pp = |p_model_azul − p_model_vermelho|."
)

with st.sidebar:
    st.header("Base do modelo")
    uploaded = st.file_uploader("Upload dados_mega_merged.xlsx", type=["xlsx"])
    if uploaded is not None:
        try:
            mega.init_from_excel(uploaded)
            st.success("Base carregada.")
        except Exception as e:
            st.error(f"Falha ao carregar base: {e}")
    st.divider()
    st.header("Stake")
    unit_brl = st.number_input("1 unidade (R$)", min_value=1.0, value=100.0, step=10.0)
    units = st.number_input("Quantas unidades apostar", min_value=0.0, value=1.0, step=0.5)

col1, col2 = st.columns(2)
with col1:
    champs_azul_raw = st.text_input("Time AZUL (5 champs)", value="Rumble, Naafiri, Anivia, Kai'Sa, Poppy")
    odd_azul_str = st.text_input("Odd time AZUL", value="2,30")
with col2:
    champs_vermelho_raw = st.text_input("Time VERMELHO (5 champs)", value="Ambessa, Xin Zhao, Ryze, Corki, Rell")
    odd_vermelho_str = st.text_input("Odd time VERMELHO", value="1,55")

if st.button("Calcular", type="primary"):
    odd_azul = parse_float(odd_azul_str)
    odd_vermelho = parse_float(odd_vermelho_str)
    champs_azul = parse_champs(champs_azul_raw)
    champs_vermelho = parse_champs(champs_vermelho_raw)

    if odd_azul is None or odd_vermelho is None:
        st.error("Odd inválida.")
        st.stop()
    if len(champs_azul) != 5 or len(champs_vermelho) != 5:
        st.error("Cada time precisa ter 5 campeões.")
        st.stop()

    try:
        p_azul, p_vermelho = mega.calcular_chance_vitoria(champs_azul, champs_vermelho, verbose=False)
    except Exception as e:
        st.error(f"Erro no modelo/base: {e}")
        st.stop()

    gap_pp = abs(p_azul - p_vermelho)

    warn = mega.sample_warning(champs_azul, champs_vermelho, min_ratio=0.70, min_median_games=15)
    if warn and warn.get("champs"):
        st.warning("⚠️ Amostra baixa: " + ", ".join(warn["champs"]))

    c1, c2, c3 = st.columns(3)
    c1.metric("p_model AZUL", f"{p_azul:.2f}%")
    c2.metric("p_model VERMELHO", f"{p_vermelho:.2f}%")
    c3.metric("pp (gap)", f"{gap_pp:.2f} pp")

    lado = pick_side(p_azul, p_vermelho)
    odd_escolhida = get_odd_for_side(lado, odd_azul, odd_vermelho)
    p_house = implied_prob_pct(odd_escolhida)
    p_model_side = p_azul if lado == "AZUL" else p_vermelho
    edge_pp = (p_model_side - p_house) if p_house is not None else None

    entra, motivo = should_bet(odd_escolhida, gap_pp)

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Lado", lado)
    d2.metric("Odd usada", f"{odd_escolhida:.2f}")
    d3.metric("p_house", f"{p_house:.2f}%" if p_house is not None else "-")
    d4.metric("Edge vs odd (pp)", f"{edge_pp:.2f}" if edge_pp is not None else "-")

    stake_brl = units * unit_brl
    if entra and units > 0:
        win_profit_u = (odd_escolhida - 1.0) * units
        lose_profit_u = -1.0 * units
        st.success(f"✅ ENTRA — {motivo}")
        st.write(f"Stake: {units:.2f}u (R$ {stake_brl:,.2f})")
        st.write(f"Se ganhar: +{win_profit_u:.2f}u (R$ {(win_profit_u*unit_brl):,.2f})")
        st.write(f"Se perder: {lose_profit_u:.2f}u (R$ {(lose_profit_u*unit_brl):,.2f})")
    else:
        st.warning(f"❌ Sem entrada — {motivo}")
