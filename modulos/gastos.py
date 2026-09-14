"""Gastos mensais: fixos, cartão de crédito (faturas e parcelas) e débito."""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db
from modulos import importar
from utils import (COR_GRUPO, SERIES, brl, fig_show, kpi, rotulo_comp, rotulo_comp_longo,
                   seletor_competencia)


def render():
    st.title("🧾 Gastos")
    c1, _ = st.columns([1, 3])
    with c1:
        comp = seletor_competencia("comp_gastos", "Competência")

    r = db.resumo_mes(comp)
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        kpi("Fixos", brl(r["fixos"]), f"pagos: {brl(r['fixos_pago'])}")
    with k2:
        kpi("Cartão (fatura)", brl(r["cartao"]), "vence conforme cada cartão")
    with k3:
        kpi("Débito / Pix", brl(r["debito"]), "saída direta da conta")
    with k4:
        cor = "#008300" if r["saldo"] >= 0 else "#e34948"
        kpi("Sobra do mês", brl(r["saldo"]), f"créditos {brl(r['creditos'])}", cor)

    aba_fix, aba_cartao, aba_deb, aba_imp = st.tabs(
        ["🏠 Fixos", "💳 Cartão de crédito", "🏦 Débito", "📥 Importar planilha"])
    with aba_fix:
        _fixos(comp)
    with aba_cartao:
        _lancamentos(comp, "CARTAO")
    with aba_deb:
        _lancamentos(comp, "DEBITO")
    with aba_imp:
        importar.render()


# ── Fixos ───────────────────────────────────────────────────────────────────
def _fixos(comp):
    df = db.fixos_do_mes(comp)
    if df.empty:
        st.info("Nenhum gasto fixo cadastrado. Cadastre em Configurações → Gastos fixos.")
        return
    st.caption("Marque o que já foi pago e ajuste o valor quando a conta vier diferente do previsto. "
               "Cada linha é gravada ao clicar em **Salvar**.")
    with st.form(f"fixos_{comp}"):
        h1, h2, h3, h4, h5 = st.columns([2.4, 1.2, 1.2, 0.9, 1.4])
        h1.markdown("**Conta**"); h2.markdown("**Previsto**"); h3.markdown("**Valor**")
        h4.markdown("**Pago**"); h5.markdown("**Pago em**")
        linhas = []
        for _, x in df.iterrows():
            a, b, c, d, e = st.columns([2.4, 1.2, 1.2, 0.9, 1.4])
            a.markdown(f"{x['nome']}  \n<span style='font-size:12px;color:#6b6a66'>vence dia {int(x['dia_vencimento'])}</span>",
                       unsafe_allow_html=True)
            b.markdown(f"<div style='padding-top:6px'>{brl(x['valor_previsto'])}</div>", unsafe_allow_html=True)
            v = c.number_input("v", value=float(x["valor"] or 0), step=10.0, format="%.2f",
                               key=f"fx_v_{comp}_{x['tipo_id']}", label_visibility="collapsed")
            p = d.checkbox("pago", value=bool(x["pago"]), key=f"fx_p_{comp}_{x['tipo_id']}",
                           label_visibility="collapsed")
            _dp0 = (pd.to_datetime(x["data_pagamento"]).date()
                    if (pd.notna(x["data_pagamento"]) and str(x["data_pagamento"]).strip()) else date.today())
            dp = e.date_input("dp", value=_dp0,
                              key=f"fx_d_{comp}_{x['tipo_id']}", label_visibility="collapsed")
            linhas.append((int(x["tipo_id"]), v, p, dp))
        if st.form_submit_button("💾 Salvar fixos do mês", type="primary"):
            for tid, v, p, dp in linhas:
                db.salvar_fixo(comp, tid, v, p, str(dp) if p else None)
            st.success("Fixos salvos.")
            st.rerun()

    tot, pago = float(df["valor"].sum()), float(df.loc[df["pago"] == 1, "valor"].sum())
    st.progress(min(1.0, pago / tot) if tot else 0.0,
                text=f"Pago {brl(pago)} de {brl(tot)} ({(pago / tot * 100) if tot else 0:.0f}%)")


# ── Cartão / Débito ─────────────────────────────────────────────────────────
def _lancamentos(comp, modalidade):
    cats = db.categorias()
    if cats.empty:
        st.warning("Cadastre categorias em Configurações.")
        return
    cartoes = db.cartoes() if modalidade == "CARTAO" else pd.DataFrame()
    if modalidade == "CARTAO" and cartoes.empty:
        st.info("Cadastre um cartão em **Configurações → Cartões** (dia de fechamento e vencimento) "
                "para lançar compras e montar as faturas.")
        return

    col_form, col_lista = st.columns([1, 1.7])
    with col_form:
        st.subheader("Novo lançamento" if modalidade == "DEBITO" else "Nova compra no cartão")
        # A modalidade fica FORA do formulario: assim a lista de categorias
        # acompanha a escolha na hora (dentro do form so atualizaria ao enviar).
        grupo = st.selectbox("Modalidade", sorted(cats["grupo"].unique().tolist()), key=f"grupo_{modalidade}")
        with st.form(f"novo_{modalidade}", clear_on_submit=True):
            cartao_nome = None
            if modalidade == "CARTAO":
                cartao_nome = st.selectbox("Cartão", cartoes["nome"].tolist())
            data = st.date_input("Data", value=date.today())
            estab = st.text_input("Estabelecimento", placeholder="Ifood, Coopercica, Posto, Enjoei...")
            cat = st.selectbox("Categoria", cats.loc[cats["grupo"] == grupo, "nome"].tolist())
            valor = st.number_input("Valor total (R$)", min_value=0.0, step=10.0, format="%.2f")
            parcelas = 1
            if modalidade == "CARTAO":
                parcelas = st.number_input("Parcelas", min_value=1, max_value=48, value=1, step=1)
            obs = st.text_input("Observação (opcional)")
            if st.form_submit_button("Lançar", type="primary", width="stretch"):
                if not estab.strip() or valor <= 0:
                    st.error("Informe estabelecimento e valor.")
                else:
                    cid = int(cats.loc[(cats["grupo"] == grupo) & (cats["nome"] == cat), "id"].iloc[0])
                    cart_id = int(cartoes.loc[cartoes["nome"] == cartao_nome, "id"].iloc[0]) if cartao_nome else None
                    db.add_lancamento(data, modalidade, cart_id, estab, cid, valor, parcelas, obs)
                    if modalidade == "CARTAO":
                        fech = int(cartoes.loc[cartoes["nome"] == cartao_nome, "dia_fechamento"].iloc[0])
                        c0 = db.competencia_cartao(data, fech)
                        st.success(f"Lançado na fatura de {rotulo_comp_longo(c0)}"
                                   + (f" (+{parcelas - 1} parcela(s) seguintes)" if parcelas > 1 else "") + ".")
                    else:
                        st.success("Lançado.")
                    st.rerun()

    with col_lista:
        titulo = "Fatura" if modalidade == "CARTAO" else "Lançamentos"
        st.subheader(f"{titulo} de {rotulo_comp_longo(comp)}")
        cart_filtro = None
        if modalidade == "CARTAO" and len(cartoes) > 1:
            esc = st.selectbox("Cartão", ["Todos"] + cartoes["nome"].tolist(), key=f"filtro_cart_{comp}")
            if esc != "Todos":
                cart_filtro = int(cartoes.loc[cartoes["nome"] == esc, "id"].iloc[0])
        df = db.lancamentos(comp, modalidade, cart_filtro)
        if df.empty:
            st.info("Nada lançado neste mês.")
        else:
            tot = float(df["valor"].sum())
            if modalidade == "CARTAO":
                for _, ca in cartoes.iterrows():
                    if cart_filtro and int(ca["id"]) != cart_filtro:
                        continue
                    sub = df[df["cartao"] == ca["nome"]]
                    if sub.empty:
                        continue
                    v = float(sub["valor"].sum())
                    lim = float(ca["limite"] or 0)
                    uso = f" · {v / lim * 100:.0f}% do limite" if lim else ""
                    st.markdown(f"**{ca['nome']}** — fatura {brl(v)} · fecha dia {int(ca['dia_fechamento'])}, "
                                f"vence dia {int(ca['dia_vencimento'])}{uso}")
            else:
                st.markdown(f"**Total:** {brl(tot)}")

            # Por modalidade (grupo)
            g = df.groupby("grupo")["valor"].sum().sort_values(ascending=True)
            fig = go.Figure(go.Bar(x=g.values, y=g.index, orientation="h",
                                   marker_color=[COR_GRUPO.get(k, "#8a8987") for k in g.index],
                                   text=[brl(v, 0) for v in g.values], textposition="outside", cliponaxis=False,
                                   hovertemplate="%{y}: R$ %{x:,.2f}<extra></extra>"))
            fig.update_layout(xaxis=dict(visible=False), margin=dict(l=8, r=90, t=8, b=8))
            fig_show(fig, 40 + 34 * len(g))

            st.markdown("**Itens**")
            for _, x in df.iterrows():
                a, b, c, d = st.columns([2.6, 1.6, 1.1, 0.5])
                parc = f" · {int(x['parcela_num'])}/{int(x['parcelas'])}" if int(x["parcelas"]) > 1 else ""
                cart = f" · {x['cartao']}" if x["cartao"] else ""
                a.markdown(f"**{x['estabelecimento']}**{parc}  \n<span style='font-size:12px;color:#6b6a66'>"
                           f"{x['grupo']} › {x['categoria']}{cart}</span>", unsafe_allow_html=True)
                b.markdown(f"<div style='text-align:right;font-variant-numeric:tabular-nums;padding-top:4px'>{brl(x['valor'])}</div>",
                           unsafe_allow_html=True)
                c.caption(str(x["data"]))
                if d.button("🗑", key=f"del_l_{x['id']}", help="Excluir (todas as parcelas, se houver)"):
                    db.del_lancamento(int(x["id"]), todas_parcelas=True)
                    st.rerun()

    # Próximas faturas (parcelas já comprometidas)
    if modalidade == "CARTAO":
        st.markdown("---")
        st.subheader("Comprometido nas próximas faturas")
        fut = db.lancamentos(de=db.somar_meses(comp, 1), ate=db.somar_meses(comp, 12), modalidade="CARTAO")
        if fut.empty:
            st.caption("Nenhuma parcela futura.")
        else:
            s = fut.groupby("competencia")["valor"].sum()
            fig = go.Figure(go.Bar(x=[rotulo_comp(c) for c in s.index], y=s.values, marker_color=SERIES[1],
                                   hovertemplate="%{x}: R$ %{y:,.2f}<extra></extra>"))
            fig_show(fig, 240)
