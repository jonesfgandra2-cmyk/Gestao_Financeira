"""Saúde Financeira: score, onde o dinheiro vai, comparativos, oportunidades e mercado."""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db
import mercado
from utils import (COR_GRUPO, COR_MODALIDADE, SERIES, STATUS, badge, brl, fig_show, kpi, pct,
                   rotulo_comp, rotulo_comp_longo, seletor_competencia)


@st.cache_data(ttl=900, show_spinner=False)
def _painel_mercado_cache(ind, moe, cri):
    """Cotacoes memorizadas por 15 min (a chave e' a selecao do usuario);
    sem isto cada clique no dashboard iria a internet de novo."""
    return mercado.painel_mercado()


def _score(r, r_ant, gastos_cat, patrimonio, meta_sobra, alerta_cartao):
    """0–100 a partir de quatro sinais simples e explicáveis."""
    pontos, motivos = 0, []
    renda = r["creditos"]
    if renda <= 0:
        return 0, [("serio", "Sem créditos lançados no mês — lance a renda para calcular o score.")]
    sobra = r["saldo"] / renda * 100
    # 1) sobra da renda (40 pts)
    p = max(0, min(40, sobra / meta_sobra * 40)) if meta_sobra else 0
    pontos += p
    motivos.append(("bom" if sobra >= meta_sobra else "serio",
                    f"Sobra de {pct(sobra, 0)} da renda (meta {pct(meta_sobra, 0)})"))
    # 2) cartão x renda (20 pts)
    cart = r["cartao"] / renda * 100
    p = 20 if cart <= alerta_cartao else max(0, 20 - (cart - alerta_cartao))
    pontos += p
    motivos.append(("bom" if cart <= alerta_cartao else "serio",
                    f"Cartão consome {pct(cart, 0)} da renda (alerta acima de {pct(alerta_cartao, 0)})"))
    # 3) fixos x renda (20 pts): até 50% ok
    fix = r["fixos"] / renda * 100
    p = 20 if fix <= 50 else max(0, 20 - (fix - 50) / 2)
    pontos += p
    motivos.append(("bom" if fix <= 50 else "atencao", f"Fixos são {pct(fix, 0)} da renda"))
    # 4) investiu no mês (20 pts)
    ap = r["aportes"] + r["planos"]
    p = 20 if ap >= renda * 0.10 else (10 if ap > 0 else 0)
    pontos += p
    motivos.append(("bom" if ap >= renda * 0.10 else ("atencao" if ap > 0 else "serio"),
                    f"Guardou {brl(ap)} ({pct(ap / renda * 100, 0)} da renda)"))
    return int(round(pontos)), motivos


def render():
    st.title("📊 Saúde Financeira")
    c1, c2 = st.columns([1, 3])
    with c1:
        comp = seletor_competencia("comp_dash", "Mês de referência")
    comp_ant = db.somar_meses(comp, -1)
    r, r_ant = db.resumo_mes(comp), db.resumo_mes(comp_ant)
    meta_sobra = db.get_config_float("meta_taxa_poupanca", 20)
    alerta_cartao = db.get_config_float("alerta_cartao_pct_renda", 35)

    # ── Mercado ─────────────────────────────────────────────────────────
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("🔄 Atualizar cotações", key="dash_atualizar_cot",
                     help="Busca de novo no Banco Central e no CoinGecko (o painel guarda por 15 min)."):
            mercado.resetar_falha()
            _painel_mercado_cache.clear()
            st.rerun()
    with st.container(border=True):
        itens = _painel_mercado_cache(db.get_config("painel_indices", ""), db.get_config("painel_moedas", ""),
                                      db.get_config("painel_criptos", ""))
        if not itens:
            st.caption("Nenhuma cotação selecionada — escolha em Configurações → Cotações.")
        cols = st.columns(max(1, len(itens)))
        for col, it in zip(cols, itens):
            v = it["valor"]
            if v is None:
                txt = "—"
            elif it["fmt"] == "pct_aa":
                txt = pct(v, 2) + " a.a."
            elif it["fmt"] == "pct_am":
                txt = pct(v, 2) + " a.m."
            elif it["fmt"] == "brl0":
                txt = brl(v, 0)
            else:
                txt = brl(v)
            col.markdown(f"<div style='font-size:11px;color:#6b6a66;text-transform:uppercase;letter-spacing:.06em'>{it['nome']}</div>"
                         f"<div style='font-size:19px;font-weight:600;font-variant-numeric:tabular-nums'>{txt}</div>"
                         f"<div style='font-size:11px;color:#8a8987'>{it['origem']}</div>", unsafe_allow_html=True)

    # ── KPIs ────────────────────────────────────────────────────────────
    def delta(a, b):
        if not b:
            return ""
        d = (a - b) / b * 100
        return f"{'▲' if d >= 0 else '▼'} {abs(d):.0f}% vs {rotulo_comp(comp_ant)}"

    k = st.columns(5)
    with k[0]:
        kpi("Créditos", brl(r["creditos"]), delta(r["creditos"], r_ant["creditos"]))
    with k[1]:
        kpi("Gastos", brl(r["gastos"]), delta(r["gastos"], r_ant["gastos"]),
            STATUS["critico"] if r["gastos"] > r["creditos"] > 0 else "#0b0b0b")
    with k[2]:
        kpi("Sobra", brl(r["saldo"]), f"{pct(r['saldo'] / r['creditos'] * 100, 0) if r['creditos'] else '—'} da renda",
            STATUS["bom"] if r["saldo"] >= 0 else STATUS["critico"])
    with k[3]:
        kpi("Guardado", brl(r["aportes"] + r["planos"]), "investimentos + objetivos")
    mov = db.rentabilidade(db.movimentos())
    ult = mov.sort_values("competencia").groupby("investimento_id").tail(1) if not mov.empty else mov
    patrimonio = float(ult["saldo_final"].sum()) if not ult.empty else 0.0
    with k[4]:
        kpi("Patrimônio", brl(patrimonio), "saldo dos investimentos")

    # ── Score ───────────────────────────────────────────────────────────
    gcat = db.gastos_por_categoria(comp)
    score, motivos = _score(r, r_ant, gcat, patrimonio, meta_sobra, alerta_cartao)
    cor = STATUS["bom"] if score >= 70 else (STATUS["atencao"] if score >= 45 else STATUS["critico"])
    s1, s2 = st.columns([1, 2.4])
    with s1:
        fig = go.Figure(go.Indicator(mode="gauge+number", value=score,
                                     number=dict(font=dict(size=40, color=cor)),
                                     gauge=dict(axis=dict(range=[0, 100], tickvals=[0, 45, 70, 100],
                                                          tickcolor="#6b6a66"),
                                                bar=dict(color=cor, thickness=0.28),
                                                bgcolor="#f0efec", borderwidth=0,
                                                steps=[dict(range=[0, 45], color="#fbeceb"),
                                                       dict(range=[45, 70], color="#fbf2e4"),
                                                       dict(range=[70, 100], color="#e6f2ef")])))
        fig.update_layout(margin=dict(l=30, r=30, t=30, b=0), title=dict(text="Score do mês", x=0.5, font=dict(size=14)))
        fig_show(fig, 220)
    with s2:
        st.markdown("**Como o score foi calculado**")
        for nivel, txt in motivos:
            st.markdown(badge(txt, nivel), unsafe_allow_html=True)
        st.caption("Sobra da renda (40) · cartão × renda (20) · fixos × renda (20) · guardou no mês (20).")

    st.markdown("---")

    # ── Onde gastamos ───────────────────────────────────────────────────
    a, b = st.columns([1, 1])
    with a:
        st.subheader("Onde o dinheiro foi")
        partes = {"Fixos": r["fixos"]}
        if not gcat.empty:
            for g, v in gcat.groupby("grupo")["valor"].sum().items():
                partes[g] = partes.get(g, 0) + float(v)
        partes = {k: v for k, v in partes.items() if v > 0}
        if not partes:
            st.info("Nenhum gasto lançado no mês.")
        else:
            s = pd.Series(partes).sort_values(ascending=True)
            fig = go.Figure(go.Bar(x=s.values, y=s.index, orientation="h",
                                   marker_color=[COR_GRUPO.get(k, "#8a8987") for k in s.index],
                                   text=[f"{brl(v, 0)} · {v / s.sum() * 100:.0f}%" for v in s.values],
                                   textposition="outside", cliponaxis=False,
                                   hovertemplate="%{y}: R$ %{x:,.2f}<extra></extra>"))
            fig.update_layout(xaxis=dict(visible=False), margin=dict(l=8, r=110, t=8, b=8))
            fig_show(fig, 60 + 36 * len(s))
    with b:
        st.subheader("Maiores gastos do mês")
        top = db.top_estabelecimentos(comp, 8)
        if top.empty:
            st.info("Sem lançamentos de cartão/débito.")
        else:
            s = top.set_index("estabelecimento")["valor"].sort_values(ascending=True)
            fig = go.Figure(go.Bar(x=s.values, y=s.index, orientation="h", marker_color=SERIES[0],
                                   text=[brl(v, 0) for v in s.values], textposition="outside", cliponaxis=False,
                                   hovertemplate="%{y}: R$ %{x:,.2f}<extra></extra>"))
            fig.update_layout(xaxis=dict(visible=False), margin=dict(l=8, r=80, t=8, b=8))
            fig_show(fig, 60 + 36 * len(s))

    # ── Comparativo mês a mês ───────────────────────────────────────────
    st.subheader("Créditos × gastos — últimos 12 meses")
    serie = db.serie_mensal(12, comp)
    x = [rotulo_comp(c) for c in serie["competencia"]]
    fig = go.Figure()
    fig.add_bar(x=x, y=serie["fixos"], name="Fixos", marker_color=COR_MODALIDADE["Fixos"],
                marker_line_color="white", marker_line_width=2, hovertemplate="%{x}<br>Fixos: R$ %{y:,.2f}<extra></extra>")
    fig.add_bar(x=x, y=serie["cartao"], name="Cartão", marker_color=COR_MODALIDADE["Cartão"],
                marker_line_color="white", marker_line_width=2, hovertemplate="%{x}<br>Cartão: R$ %{y:,.2f}<extra></extra>")
    fig.add_bar(x=x, y=serie["debito"], name="Débito", marker_color=COR_MODALIDADE["Débito"],
                marker_line_color="white", marker_line_width=2, hovertemplate="%{x}<br>Débito: R$ %{y:,.2f}<extra></extra>")
    fig.add_scatter(x=x, y=serie["creditos"], name="Créditos", mode="lines+markers",
                    line=dict(color="#0b0b0b", width=2), marker=dict(size=7, color="#0b0b0b"),
                    hovertemplate="%{x}<br>Créditos: R$ %{y:,.2f}<extra></extra>")
    fig.update_layout(barmode="stack")
    fig_show(fig, 320)

    # ── Comparativo por modalidade: este mês x anterior ─────────────────
    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.subheader(f"{rotulo_comp(comp)} × {rotulo_comp(comp_ant)} por modalidade")
        g_now = gcat.groupby("grupo")["valor"].sum() if not gcat.empty else pd.Series(dtype=float)
        g_ant_df = db.gastos_por_categoria(comp_ant)
        g_ant = g_ant_df.groupby("grupo")["valor"].sum() if not g_ant_df.empty else pd.Series(dtype=float)
        comp_df = pd.DataFrame({"atual": g_now, "anterior": g_ant}).fillna(0)
        comp_df.loc["Fixos"] = [r["fixos"], r_ant["fixos"]]
        comp_df = comp_df[(comp_df["atual"] > 0) | (comp_df["anterior"] > 0)]
        if comp_df.empty:
            st.info("Sem dados para comparar.")
        else:
            comp_df["var"] = (comp_df["atual"] - comp_df["anterior"])
            comp_df = comp_df.sort_values("var")
            cores = [STATUS["critico"] if v > 0 else STATUS["bom"] for v in comp_df["var"]]
            fig = go.Figure(go.Bar(x=comp_df["var"], y=comp_df.index, orientation="h", marker_color=cores,
                                   text=[("+" if v > 0 else "−") + brl(abs(v), 0) for v in comp_df["var"]],
                                   textposition="outside", cliponaxis=False,
                                   hovertemplate="%{y}<br>Variação: R$ %{x:,.2f}<extra></extra>"))
            fig.update_layout(xaxis=dict(visible=False), margin=dict(l=8, r=90, t=8, b=8))
            fig_show(fig, 60 + 36 * len(comp_df))
            st.caption("Vermelho gastou mais que no mês anterior; verde gastou menos.")

    # ── Oportunidades ───────────────────────────────────────────────────
    with c2:
        st.subheader("Oportunidades de melhora")
        dicas = []
        renda = r["creditos"]
        if renda > 0:
            if r["saldo"] < 0:
                dicas.append(("critico", f"Gastos superaram a renda em {brl(-r['saldo'])}."))
            if r["cartao"] / renda * 100 > alerta_cartao:
                dicas.append(("serio", f"Cartão em {pct(r['cartao'] / renda * 100, 0)} da renda — acima do alerta de {pct(alerta_cartao, 0)}."))
            if (r["aportes"] + r["planos"]) < renda * 0.10:
                dicas.append(("atencao", "Guardou menos de 10% da renda este mês."))
        try:
            for g, row in comp_df.iterrows():
                if row["anterior"] > 0 and row["atual"] > row["anterior"] * 1.25 and row["atual"] - row["anterior"] > 100:
                    dicas.append(("atencao", f"{g} subiu {pct((row['atual'] / row['anterior'] - 1) * 100, 0)} "
                                             f"em relação a {rotulo_comp(comp_ant)} (+{brl(row['var'], 0)})."))
        except Exception:
            pass
        if not gcat.empty:
            cat_top = gcat.groupby("categoria")["valor"].sum().sort_values(ascending=False)
            if renda > 0 and cat_top.iloc[0] / renda > 0.15:
                dicas.append(("atencao", f"{cat_top.index[0]} sozinha leva {pct(cat_top.iloc[0] / renda * 100, 0)} da renda."))
        fixos = db.fixos_do_mes(comp)
        if not fixos.empty:
            acima = fixos[(fixos["valor_previsto"] > 0) & (fixos["valor"] > fixos["valor_previsto"] * 1.15)]
            for _, f in acima.iterrows():
                dicas.append(("atencao", f"{f['nome']} veio {brl(f['valor'] - f['valor_previsto'], 0)} acima do previsto."))
        fut = db.lancamentos(de=db.somar_meses(comp, 1), ate=db.somar_meses(comp, 3), modalidade="CARTAO")
        if not fut.empty and renda > 0:
            prox = float(fut[fut["competencia"] == db.somar_meses(comp, 1)]["valor"].sum())
            if prox > renda * 0.25:
                dicas.append(("atencao", f"Já há {brl(prox, 0)} comprometidos na fatura de {rotulo_comp(db.somar_meses(comp, 1))} (parcelas)."))
        if not mov.empty:
            ult_m = ult.copy()
            for _, m in ult_m.iterrows():
                cdi_m, _ = mercado.cdi_mensal(m["competencia"])
                if cdi_m and pd.notna(m["rentab_pct"]) and m["rentab_pct"] < cdi_m * db.get_config_float("limite_baixo_rendimento", 70) / 100:
                    dicas.append(("atencao", f"Investimento {m['nome']} rendeu {pct(m['rentab_pct'], 2)} em {rotulo_comp(m['competencia'])}, abaixo do CDI."))
        if not dicas:
            dicas.append(("bom", "Nada fora do lugar neste mês. Mantenha o ritmo."))
        for nivel, txt in dicas[:8]:
            st.markdown(badge(txt, nivel), unsafe_allow_html=True)
            st.markdown("")

    # ── Evolução do patrimônio ──────────────────────────────────────────
    if not mov.empty:
        st.subheader("Patrimônio investido (12 meses)")
        comps = [db.somar_meses(comp, -i) for i in range(11, -1, -1)]
        piv = (mov.pivot_table(index="competencia", columns="nome", values="saldo_final", aggfunc="last")
               .reindex(sorted(set(mov["competencia"]) | set(comps))).ffill().reindex(comps).fillna(0))
        tot = piv.sum(axis=1)
        fig = go.Figure(go.Scatter(x=[rotulo_comp(c) for c in tot.index], y=tot.values, mode="lines+markers",
                                   line=dict(color=SERIES[2], width=2), marker=dict(size=7),
                                   fill="tozeroy", fillcolor="rgba(27,175,122,.12)",
                                   hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>"))
        fig_show(fig, 260)
