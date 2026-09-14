"""Créditos do mês: salário, horas extras, 13º, férias, bônus..."""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db
from utils import SERIES, brl, fig_show, kpi, rotulo_comp, seletor_competencia


def render():
    st.title("💵 Créditos do mês")
    c1, c2 = st.columns([1, 3])
    with c1:
        comp = seletor_competencia("comp_cred", "Competência")

    tipos = db.tipos_credito()
    df = db.creditos(comp)
    total = float(df["valor"].sum()) if not df.empty else 0.0

    k1, k2, k3 = st.columns(3)
    with k1:
        kpi("Total do mês", brl(total), f"{len(df)} lançamento(s)")
    with k2:
        sal = float(df.loc[df["tipo"] == "Salário", "valor"].sum()) if not df.empty else 0.0
        kpi("Salário", brl(sal), "renda fixa")
    with k3:
        kpi("Extras", brl(total - sal), "horas extras, 13º, bônus...")

    st.markdown("---")
    col_form, col_lista = st.columns([1, 1.6])

    with col_form:
        st.subheader("Novo crédito")
        with st.form("novo_credito", clear_on_submit=True):
            tipo = st.selectbox("Tipo", tipos["nome"].tolist())
            valor = st.number_input("Valor (R$)", min_value=0.0, step=100.0, format="%.2f")
            data = st.date_input("Data de recebimento", value=date.today())
            desc = st.text_input("Descrição (opcional)")
            if st.form_submit_button("Lançar", type="primary", width="stretch"):
                if valor <= 0:
                    st.error("Informe um valor maior que zero.")
                else:
                    tid = int(tipos.loc[tipos["nome"] == tipo, "id"].iloc[0])
                    db.add_credito(comp, data, tid, desc, valor)
                    st.success("Crédito lançado.")
                    st.rerun()

    with col_lista:
        st.subheader("Lançamentos do mês")
        if df.empty:
            st.info("Nenhum crédito neste mês.")
        else:
            for _, r in df.iterrows():
                a, b, c, d = st.columns([2.2, 2, 1.4, 0.6])
                a.markdown(f"**{r['tipo']}**  \n<span style='color:#6b6a66;font-size:12px'>{r['descricao'] or ''}</span>",
                           unsafe_allow_html=True)
                b.markdown(f"<div style='text-align:right;font-variant-numeric:tabular-nums'>{brl(r['valor'])}</div>",
                           unsafe_allow_html=True)
                c.caption(str(r["data"]))
                if d.button("🗑", key=f"del_cred_{r['id']}", help="Excluir"):
                    db.del_credito(int(r["id"]))
                    st.rerun()

    # Evolução dos últimos 12 meses
    st.markdown("---")
    st.subheader("Evolução dos créditos (12 meses)")
    hist = db.creditos()
    if hist.empty:
        st.caption("Sem histórico ainda.")
        return
    hoje = db.competencia_de(date.today())
    comps = [db.somar_meses(hoje, -i) for i in range(11, -1, -1)]
    piv = (hist[hist["competencia"].isin(comps)]
           .pivot_table(index="competencia", columns="tipo", values="valor", aggfunc="sum")
           .reindex(comps).fillna(0))
    fig = go.Figure()
    for i, col in enumerate(piv.columns):
        fig.add_bar(x=[rotulo_comp(c) for c in piv.index], y=piv[col], name=col,
                    marker_color=SERIES[i % len(SERIES)], marker_line_color="white", marker_line_width=2,
                    hovertemplate="%{x}<br>" + col + ": R$ %{y:,.2f}<extra></extra>")
    fig.update_layout(barmode="stack", yaxis_title=None, xaxis_title=None)
    fig_show(fig, 300)
