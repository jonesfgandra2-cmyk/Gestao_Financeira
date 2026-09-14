"""Formatação, competências e tema dos gráficos."""
from __future__ import annotations

from datetime import date

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

import db

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

# Paleta categórica validada (ordem fixa; nunca reordenar por ranking).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQ_AZUL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
STATUS = {"bom": "#008300", "atencao": "#eda100", "serio": "#eb6834", "critico": "#e34948"}
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e6e5e1"

# Cor fixa por grupo de gasto (segue a entidade, não a posição no gráfico)
COR_GRUPO = {
    "Fixos": SERIES[6], "Alimentação/Lazer": SERIES[1], "Despesa Casa": SERIES[0],
    "Transporte": SERIES[3], "Compras Diversas": SERIES[4], "Saúde": SERIES[2],
    "Educação": SERIES[5], "Outros": "#8a8987",
}
COR_MODALIDADE = {"Fixos": SERIES[6], "Cartão": SERIES[1], "Débito": SERIES[0]}


def brl(v, casas=2) -> str:
    try:
        v = float(v or 0)
    except Exception:
        return "R$ 0,00"
    s = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def brl_curto(v) -> str:
    v = float(v or 0)
    if abs(v) >= 1_000_000:
        return f"R$ {v/1_000_000:.1f} mi".replace(".", ",")
    if abs(v) >= 10_000:
        return f"R$ {v/1_000:.0f} mil"
    return brl(v, 0)


def pct(v, casas=1) -> str:
    try:
        return f"{float(v):.{casas}f}%".replace(".", ",")
    except Exception:
        return "—"


def rotulo_comp(comp: str) -> str:
    return f"{MESES[int(comp[5:7]) - 1]}/{comp[2:4]}"


def rotulo_comp_longo(comp: str) -> str:
    nomes = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
             "Setembro", "Outubro", "Novembro", "Dezembro"]
    return f"{nomes[int(comp[5:7]) - 1]} de {comp[:4]}"


def seletor_competencia(key="comp", label="Mês", padrao=None) -> str:
    """Selectbox de competência (últimos 24 meses + 3 futuros)."""
    hoje = db.competencia_de(date.today())
    opcoes = [db.somar_meses(hoje, i) for i in range(3, -24, -1)]
    padrao = padrao or hoje
    idx = opcoes.index(padrao) if padrao in opcoes else 3
    return st.selectbox(label, opcoes, index=idx, format_func=rotulo_comp_longo, key=key)


# ── Tema Plotly ─────────────────────────────────────────────────────────────
def _tema():
    t = go.layout.Template()
    t.layout = dict(
        font=dict(family="Inter, -apple-system, Segoe UI, sans-serif", size=13, color=INK),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=36, b=8),
        colorway=SERIES,
        xaxis=dict(showgrid=False, zeroline=False, linecolor=GRID, tickfont=dict(color=INK2)),
        yaxis=dict(gridcolor=GRID, zeroline=False, showline=False, tickfont=dict(color=INK2)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=INK2)),
        hoverlabel=dict(bgcolor="white", font=dict(color=INK)),
        bargap=0.35,
    )
    return t


pio.templates["financeiro"] = _tema()
pio.templates.default = "financeiro"


def fig_show(fig, height=320, key=None):
    fig.update_layout(height=height)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=key)


def kpi(label, valor, apoio="", cor=INK):
    st.markdown(f"""
    <div style="border:1px solid #e3e2de;border-radius:8px;padding:14px 16px;background:#fff;height:100%">
      <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6b6a66;font-weight:600">{label}</div>
      <div style="font-size:24px;font-weight:600;color:{cor};margin:6px 0 2px;font-variant-numeric:tabular-nums">{valor}</div>
      <div style="font-size:12px;color:#6b6a66">{apoio}</div>
    </div>""", unsafe_allow_html=True)


def badge(texto, nivel="bom"):
    cor = STATUS.get(nivel, INK2)
    icone = {"bom": "✔", "atencao": "▲", "serio": "▲", "critico": "✖"}.get(nivel, "•")
    return (f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;'
            f'font-weight:600;color:{cor};border:1px solid {cor};background:{cor}12">{icone} {texto}</span>')
