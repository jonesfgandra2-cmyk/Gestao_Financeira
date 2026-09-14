"""Planejamento futuro: viagem, troca de carro, casa, celular... com aportes."""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db
from utils import SERIES, STATUS, brl, fig_show, kpi

PRIORIDADE = {1: "Alta", 2: "Média", 3: "Baixa"}


def _meses_ate(data_alvo):
    if not data_alvo:
        return None
    d = pd.to_datetime(data_alvo).date()
    hoje = date.today()
    return max(0, (d.year - hoje.year) * 12 + (d.month - hoje.month))


def render():
    st.title("🎯 Planejamento futuro")
    df = db.planos()
    andamento = df[df["status"] == "Em andamento"] if not df.empty else df

    k1, k2, k3 = st.columns(3)
    alvo = float(andamento["valor_alvo"].sum()) if not andamento.empty else 0.0
    guard = float(andamento["guardado"].sum()) if not andamento.empty else 0.0
    with k1:
        kpi("Objetivos em andamento", str(len(andamento)), "planos ativos")
    with k2:
        kpi("Total dos objetivos", brl(alvo), "valor alvo somado")
    with k3:
        kpi("Já guardado", brl(guard), f"{(guard / alvo * 100) if alvo else 0:.0f}% do total")

    col_form, col_lista = st.columns([1, 1.8])
    with col_form:
        st.subheader("Novo objetivo")
        with st.form("novo_plano", clear_on_submit=True):
            nome = st.text_input("Nome", placeholder="Viagem para o Nordeste, Civic 2024...")
            tipo = st.selectbox("Tipo", db.TIPOS_PLANO)
            valor = st.number_input("Valor alvo (R$)", min_value=0.0, step=500.0, format="%.2f")
            data_alvo = st.date_input("Quando", value=date.today().replace(year=date.today().year + 1))
            prio = st.select_slider("Prioridade", options=[1, 2, 3], value=2, format_func=lambda v: PRIORIDADE[v])
            obs = st.text_area("Observações", height=68)
            if st.form_submit_button("Cadastrar", type="primary", width="stretch"):
                if not nome.strip() or valor <= 0:
                    st.error("Informe nome e valor alvo.")
                else:
                    db.add_plano(nome, tipo, valor, data_alvo, prio, obs)
                    st.success("Objetivo cadastrado.")
                    st.rerun()

    with col_lista:
        st.subheader("Objetivos")
        if df.empty:
            st.info("Nenhum objetivo cadastrado.")
        for _, p in df.iterrows():
            guardado = float(p["guardado"])
            falta = max(0.0, float(p["valor_alvo"]) - guardado)
            prog = min(1.0, guardado / float(p["valor_alvo"])) if p["valor_alvo"] else 0.0
            meses = _meses_ate(p["data_alvo"])
            mensal = (falta / meses) if meses else falta
            concluido = p["status"] == "Concluído"
            titulo = f"{'✅ ' if concluido else ''}{p['nome']} · {p['tipo']} · {PRIORIDADE.get(int(p['prioridade']), '')}"
            with st.expander(titulo, expanded=False):
                st.progress(prog, text=f"{brl(guardado)} de {brl(p['valor_alvo'])} ({prog * 100:.0f}%)")
                a, b, c = st.columns(3)
                a.metric("Falta", brl(falta))
                b.metric("Prazo", f"{meses} mês(es)" if meses is not None else "—",
                         help=str(p["data_alvo"] or ""))
                if meses == 0 and falta > 0 and not concluido:
                    c.metric("Por mês", "prazo vencido")
                else:
                    c.metric("Guardar por mês", brl(mensal) if falta > 0 else "concluído")
                if p["obs"]:
                    st.caption(p["obs"])

                if not concluido:
                    with st.form(f"aporte_{p['id']}", clear_on_submit=True):
                        x, y, z = st.columns([1.2, 1.2, 1])
                        va = x.number_input("Aporte (R$)", min_value=0.0, step=100.0, format="%.2f",
                                            key=f"va_{p['id']}")
                        da = y.date_input("Data", value=date.today(), key=f"da_{p['id']}")
                        if z.form_submit_button("＋ Guardar"):
                            if va > 0:
                                db.add_aporte_plano(int(p["id"]), da, va)
                                st.rerun()
                ap = db.aportes_plano(int(p["id"]))
                if not ap.empty:
                    st.dataframe(ap[["data", "valor"]].rename(columns={"data": "Data", "valor": "Valor"})
                                 .style.format({"Valor": lambda v: brl(v)}),
                                 hide_index=True, width="stretch", height=min(200, 40 + 35 * len(ap)))
                b1, b2, b3 = st.columns(3)
                if not concluido and b1.button("Concluir", key=f"ok_{p['id']}"):
                    db.set_plano_status(int(p["id"]), "Concluído"); st.rerun()
                if concluido and b1.button("Reabrir", key=f"re_{p['id']}"):
                    db.set_plano_status(int(p["id"]), "Em andamento"); st.rerun()
                if b3.button("Excluir", key=f"del_p_{p['id']}"):
                    db.del_plano(int(p["id"])); st.rerun()

    if not andamento.empty:
        st.markdown("---")
        st.subheader("Quanto falta em cada objetivo")
        d = andamento.sort_values("valor_alvo", ascending=True)
        fig = go.Figure()
        fig.add_bar(y=d["nome"], x=d["guardado"], orientation="h", name="Guardado", marker_color=SERIES[2],
                    marker_line_color="white", marker_line_width=2,
                    hovertemplate="%{y}<br>Guardado: R$ %{x:,.2f}<extra></extra>")
        fig.add_bar(y=d["nome"], x=(d["valor_alvo"] - d["guardado"]).clip(lower=0), orientation="h",
                    name="Falta", marker_color="#d9d8d3", marker_line_color="white", marker_line_width=2,
                    hovertemplate="%{y}<br>Falta: R$ %{x:,.2f}<extra></extra>")
        fig.update_layout(barmode="stack", xaxis_title=None)
        fig_show(fig, 80 + 40 * len(d))
