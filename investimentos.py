"""Investimentos: lançamentos mês a mês, evolução, rendimento x CDI, metas."""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db
import mercado
from utils import (SERIES, STATUS, badge, brl, fig_show, kpi, pct, rotulo_comp, rotulo_comp_longo,
                   seletor_competencia)


def _classificar(rentab_pct, cdi_mes):
    """Rótulo de desempenho contra o CDI do mês."""
    if rentab_pct is None or pd.isna(rentab_pct) or not cdi_mes:
        return "—", "neutro"
    baixo = db.get_config_float("limite_baixo_rendimento", 70) / 100
    alto = db.get_config_float("limite_oportunidade", 120) / 100
    razao = rentab_pct / cdi_mes
    if rentab_pct < 0:
        return f"Perda ({pct(rentab_pct)})", "critico"
    if razao < baixo:
        return f"Baixo rendimento ({razao * 100:.0f}% do CDI)", "serio"
    if razao > alto:
        return f"Destaque ({razao * 100:.0f}% do CDI)", "bom"
    return f"Na média ({razao * 100:.0f}% do CDI)", "atencao"


def render():
    st.title("📈 Investimentos")
    invs = db.investimentos()
    mov = db.rentabilidade(db.movimentos())
    hoje = db.competencia_de(date.today())

    # ── Patrimônio atual ────────────────────────────────────────────────
    ultimo = (mov.sort_values("competencia").groupby("investimento_id").tail(1)
              if not mov.empty else pd.DataFrame())
    patrimonio = float(ultimo["saldo_final"].sum()) if not ultimo.empty else 0.0
    aportado = float(mov["aporte"].sum() - mov["resgate"].sum()) if not mov.empty else 0.0
    rend_total = float(mov["rendimento"].sum()) if not mov.empty else 0.0
    cdi_mes, cdi_orig = mercado.cdi_mensal(hoje)

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        kpi("Patrimônio", brl(patrimonio), f"{len(invs)} investimento(s)")
    with k2:
        kpi("Aportado (líquido)", brl(aportado), "aportes − resgates")
    with k3:
        kpi("Rendimento acumulado", brl(rend_total),
            f"{(rend_total / aportado * 100) if aportado else 0:.1f}% sobre o aportado",
            STATUS["bom"] if rend_total >= 0 else STATUS["critico"])
    with k4:
        kpi("CDI do mês", pct(cdi_mes, 2) + " a.m.", f"fonte: {cdi_orig}")

    aba_lanc, aba_evo, aba_meta, aba_cad = st.tabs(
        ["📝 Lançar mês", "📊 Evolução e rendimento", "🎯 Metas", "🗂 Cadastro"])

    with aba_cad:
        _cadastro(invs)
    with aba_lanc:
        _lancar(invs, mov)
    with aba_evo:
        _evolucao(invs, mov)
    with aba_meta:
        _metas(mov, patrimonio, aportado)


# ── Cadastro ────────────────────────────────────────────────────────────────
def _cadastro(invs):
    c1, c2 = st.columns([1, 1.6])
    with c1:
        st.subheader("Novo investimento")
        with st.form("novo_inv", clear_on_submit=True):
            nome = st.text_input("Nome", placeholder="CDB Nubank 110%, Tesouro Selic 2029, Bitcoin...")
            tipo = st.selectbox("Tipo", list(db.TIPOS_INVESTIMENTO))
            inst = st.text_input("Instituição / corretora")
            cod = st.text_input("Código do ativo (só cripto: BTC, ETH, SOL...)", placeholder="BTC")
            if st.form_submit_button("Cadastrar", type="primary", width="stretch"):
                if not nome.strip():
                    st.error("Informe o nome.")
                else:
                    db.add_investimento(nome, tipo, inst, cod)
                    st.success("Cadastrado.")
                    st.rerun()
    with c2:
        st.subheader("Cadastrados")
        if invs.empty:
            st.info("Nenhum investimento ainda.")
        for _, i in invs.iterrows():
            a, b = st.columns([5, 1])
            extra = f" · {i['ativo_codigo']}" if i["ativo_codigo"] else ""
            a.markdown(f"**{i['nome']}** — {i['tipo']}{extra}  \n<span style='font-size:12px;color:#6b6a66'>"
                       f"{i['instituicao'] or ''} · {i['moeda']}</span>", unsafe_allow_html=True)
            if b.button("Arquivar", key=f"arq_inv_{i['id']}"):
                db.set_investimento_ativo(int(i["id"]), 0); st.rerun()


# ── Lançar mês ──────────────────────────────────────────────────────────────
def _lancar(invs, mov):
    if invs.empty:
        st.info("Cadastre um investimento na aba **Cadastro**.")
        return
    c1, c2 = st.columns([1, 1.4])
    with c1:
        comp = seletor_competencia("comp_inv", "Competência")
        nome = st.selectbox("Investimento", invs["nome"].tolist(), key="inv_sel")
    inv = invs[invs["nome"] == nome].iloc[0]
    iid = int(inv["id"])
    moeda = inv["moeda"]
    precisa_cot = db.TIPOS_INVESTIMENTO.get(inv["tipo"], ("BRL", False))[1]

    ant = mov[(mov["investimento_id"] == iid) & (mov["competencia"] < comp)]
    saldo_ant = float(ant.sort_values("competencia")["saldo_final"].iloc[-1]) if not ant.empty else 0.0
    atual = mov[(mov["investimento_id"] == iid) & (mov["competencia"] == comp)]
    qtd_ant = db.quantidade_acumulada(iid, db.somar_meses(comp, -1)) if precisa_cot else 0.0

    cot, cot_orig = (mercado.cotacao(inv["ativo_codigo"], moeda) if precisa_cot else (1.0, "BRL"))

    with c2:
        st.markdown(f"**{rotulo_comp_longo(comp)}** · saldo anterior **{brl(saldo_ant)}**"
                    + (f" · posição anterior **{qtd_ant:,.6f} {inv['ativo_codigo'] or moeda}**".replace(",", "X").replace(".", ",").replace("X", ".")
                       if precisa_cot else ""))
        if precisa_cot:
            st.caption(f"Cotação de referência: {brl(cot) if cot else '—'} ({cot_orig}). "
                       "Ajuste abaixo se quiser usar outra.")
        with st.form(f"mov_{iid}_{comp}"):
            a, b = st.columns(2)
            aporte = a.number_input("Aporte no mês (R$)", min_value=0.0, step=100.0, format="%.2f",
                                    value=float(atual["aporte"].iloc[0]) if not atual.empty else 0.0)
            resgate = b.number_input("Resgate no mês (R$)", min_value=0.0, step=100.0, format="%.2f",
                                     value=float(atual["resgate"].iloc[0]) if not atual.empty else 0.0)
            if precisa_cot:
                x, y = st.columns(2)
                qtd = x.number_input(f"Quantidade comprada (−) vendida em {inv['ativo_codigo'] or moeda}",
                                     step=0.0001, format="%.6f",
                                     value=float(atual["quantidade"].iloc[0]) if (not atual.empty and pd.notna(atual["quantidade"].iloc[0])) else 0.0)
                cot_in = y.number_input("Cotação de fechamento (R$)", min_value=0.0, step=0.01, format="%.4f",
                                        value=float(atual["cotacao"].iloc[0]) if (not atual.empty and pd.notna(atual["cotacao"].iloc[0])) else float(cot or 0))
                pos = qtd_ant + qtd
                saldo_calc = pos * cot_in
                st.caption(f"Posição ao fim do mês: {pos:,.6f} × {brl(cot_in)} = **{brl(saldo_calc)}** "
                           "(recalculado ao salvar)".replace(",", "X").replace(".", ",").replace("X", "."))
                usar_calc = st.checkbox("Usar o saldo calculado pela cotação", value=True)
            else:
                qtd, cot_in, saldo_calc, usar_calc = None, None, None, False
            saldo = st.number_input("Saldo final do mês (R$) — o que o extrato mostra", min_value=0.0, step=100.0,
                                    format="%.2f",
                                    value=float(atual["saldo_final"].iloc[0]) if not atual.empty else float(saldo_ant + 0))
            obs = st.text_input("Observação")
            if st.form_submit_button("💾 Salvar mês", type="primary", width="stretch"):
                sf = saldo_calc if (precisa_cot and usar_calc) else saldo
                db.salvar_movimento(iid, comp, aporte, resgate, sf, qtd, cot_in, obs)
                st.success("Movimento salvo.")
                st.rerun()

    st.markdown("---")
    hist = db.rentabilidade(db.movimentos(iid))
    if hist.empty:
        st.caption("Sem lançamentos para este investimento.")
        return
    st.subheader(f"Histórico — {nome}")
    for _, m in hist.sort_values("competencia", ascending=False).iterrows():
        cdi_m, _ = mercado.cdi_mensal(m["competencia"])
        rot, nivel = _classificar(m["rentab_pct"], cdi_m)
        a, b, c, d, e = st.columns([1, 1.3, 1.3, 2.2, 0.5])
        a.markdown(f"**{rotulo_comp(m['competencia'])}**")
        b.markdown(f"saldo {brl(m['saldo_final'])}")
        c.markdown(f"aporte {brl(m['aporte'])}" + (f" · resg. {brl(m['resgate'])}" if m["resgate"] else ""))
        d.markdown(f"rend. {brl(m['rendimento'])} ({pct(m['rentab_pct'], 2)}) {badge(rot, nivel)}",
                   unsafe_allow_html=True)
        if e.button("🗑", key=f"del_mov_{m['id']}"):
            db.del_movimento(int(m["id"])); st.rerun()


# ── Evolução ────────────────────────────────────────────────────────────────
def _evolucao(invs, mov):
    if mov.empty:
        st.info("Lance os saldos mensais para ver a evolução.")
        return
    hoje = db.competencia_de(date.today())
    n = st.select_slider("Período", options=[6, 12, 24, 36], value=12, format_func=lambda v: f"{v} meses")
    de = db.somar_meses(hoje, -(n - 1))
    comps = [db.somar_meses(hoje, -i) for i in range(n - 1, -1, -1)]

    # saldo por investimento por mês (carry-forward do último saldo conhecido)
    piv = (mov.pivot_table(index="competencia", columns="nome", values="saldo_final", aggfunc="last")
           .reindex(sorted(set(mov["competencia"]) | set(comps))).ffill().reindex(comps).fillna(0))
    nomes = list(piv.columns)
    fig = go.Figure()
    for i, col in enumerate(nomes):
        fig.add_scatter(x=[rotulo_comp(c) for c in piv.index], y=piv[col], name=col, mode="lines",
                        stackgroup="one", line=dict(width=1.5, color=SERIES[i % len(SERIES)]),
                        hovertemplate="%{x}<br>" + col + ": R$ %{y:,.2f}<extra></extra>")
    fig.update_layout(yaxis_title=None)
    st.subheader("Patrimônio por investimento")
    fig_show(fig, 340)

    # rendimento mensal total x CDI
    st.subheader("Rendimento do mês × CDI")
    tot = mov[mov["competencia"] >= de].groupby("competencia").agg(
        rendimento=("rendimento", "sum"), base=("saldo_anterior", "sum"), aporte=("aporte", "sum")).reindex(comps)
    tot["rentab"] = tot["rendimento"] / (tot["base"] + tot["aporte"]).where((tot["base"] + tot["aporte"]) > 0) * 100
    tot["cdi"] = [mercado.cdi_mensal(c)[0] for c in tot.index]
    tot["poup"] = [mercado.poupanca_mensal(c)[0] for c in tot.index]
    x = [rotulo_comp(c) for c in tot.index]
    fig2 = go.Figure()
    fig2.add_bar(x=x, y=tot["rentab"], name="Carteira", marker_color=SERIES[0],
                 hovertemplate="%{x}<br>Carteira: %{y:.2f}%<extra></extra>")
    fig2.add_scatter(x=x, y=tot["cdi"], name="CDI", mode="lines+markers", line=dict(color=SERIES[1], width=2),
                     marker=dict(size=7), hovertemplate="%{x}<br>CDI: %{y:.2f}%<extra></extra>")
    fig2.add_scatter(x=x, y=tot["poup"], name="Poupança", mode="lines", line=dict(color=SERIES[2], width=2, dash="dot"),
                     hovertemplate="%{x}<br>Poupança: %{y:.2f}%<extra></extra>")
    fig2.update_layout(yaxis=dict(ticksuffix="%"))
    fig_show(fig2, 300)

    # Situação de cada investimento no último mês lançado
    st.subheader("Situação por investimento (último mês lançado)")
    ult = mov.sort_values("competencia").groupby("investimento_id").tail(1)
    linhas = []
    for _, m in ult.iterrows():
        cdi_m, _ = mercado.cdi_mensal(m["competencia"])
        rot, nivel = _classificar(m["rentab_pct"], cdi_m)
        # média dos últimos 3 meses
        h = mov[mov["investimento_id"] == m["investimento_id"]].sort_values("competencia").tail(3)
        med3 = float(h["rentab_pct"].mean()) if not h.empty else None
        linhas.append({"Investimento": m["nome"], "Tipo": m["tipo"], "Mês": rotulo_comp(m["competencia"]),
                       "Saldo": m["saldo_final"], "Rend. mês": m["rendimento"], "Rentab. mês": m["rentab_pct"],
                       "Média 3m": med3, "Situação": badge(rot, nivel)})
    dfv = pd.DataFrame(linhas).sort_values("Saldo", ascending=False)
    html = "<table style='width:100%;border-collapse:collapse;font-size:13.5px'>"
    html += "<tr style='color:#6b6a66;font-size:11px;text-transform:uppercase;letter-spacing:.06em'>" + "".join(
        f"<th style='text-align:left;padding:8px 6px;border-bottom:1px solid #ddd'>{c}</th>" for c in dfv.columns) + "</tr>"
    for _, r in dfv.iterrows():
        html += "<tr>" + "".join(
            f"<td style='padding:8px 6px;border-bottom:1px solid #eee'>"
            f"{brl(r[c]) if c in ('Saldo', 'Rend. mês') else (pct(r[c], 2) if c in ('Rentab. mês', 'Média 3m') else r[c])}</td>"
            for c in dfv.columns) + "</tr>"
    st.markdown(html + "</table>", unsafe_allow_html=True)

    piores = [l for l in linhas if "Baixo" in l["Situação"] or "Perda" in l["Situação"]]
    melhores = [l for l in linhas if "Destaque" in l["Situação"]]
    if piores:
        st.warning("**Baixo rendimento:** " + ", ".join(l["Investimento"] for l in piores)
                   + ". Vale comparar com um CDB de 100% do CDI ou Tesouro Selic.")
    if melhores:
        st.success("**Oportunidade / destaque:** " + ", ".join(l["Investimento"] for l in melhores)
                   + " rendendo acima do CDI — considere concentrar os próximos aportes.")


# ── Metas ───────────────────────────────────────────────────────────────────
def _metas(mov, patrimonio, aportado):
    hoje = db.competencia_de(date.today())
    c1, c2 = st.columns([1, 1.6])
    with c1:
        st.subheader("Nova meta")
        with st.form("nova_meta", clear_on_submit=True):
            tipo = st.selectbox("Tipo", ["mensal", "anual", "prazo"],
                                format_func=lambda t: {"mensal": "Aporte mensal", "anual": "Aporte no ano",
                                                       "prazo": "Patrimônio em X anos"}[t])
            valor = st.number_input("Valor (R$)", min_value=0.0, step=100.0, format="%.2f")
            anos = st.number_input("Anos (só para 'Patrimônio em X anos')", min_value=1, max_value=50, value=5)
            desc = st.text_input("Descrição", placeholder="Ex.: 1 milhão em 10 anos")
            if st.form_submit_button("Salvar meta", type="primary", width="stretch"):
                if valor <= 0:
                    st.error("Informe o valor.")
                else:
                    db.add_meta(tipo, desc, valor, anos if tipo == "prazo" else None)
                    st.rerun()
    with c2:
        st.subheader("Acompanhamento")
        ms = db.metas()
        if ms.empty:
            st.info("Nenhuma meta cadastrada.")
        for _, m in ms.iterrows():
            with st.container(border=True):
                if m["tipo"] == "mensal":
                    feito = float(mov.loc[mov["competencia"] == hoje, "aporte"].sum()) if not mov.empty else 0.0
                    p = min(1.0, feito / m["valor"]) if m["valor"] else 0
                    st.markdown(f"**Aporte mensal** · {m['descricao'] or ''}")
                    st.progress(p, text=f"{brl(feito)} de {brl(m['valor'])} em {rotulo_comp(hoje)} ({p * 100:.0f}%)")
                elif m["tipo"] == "anual":
                    ano = hoje[:4]
                    feito = float(mov.loc[mov["competencia"].str.startswith(ano), "aporte"].sum()) if not mov.empty else 0.0
                    p = min(1.0, feito / m["valor"]) if m["valor"] else 0
                    mes_n = int(hoje[5:7])
                    ritmo = feito / mes_n * 12
                    st.markdown(f"**Aporte no ano {ano}** · {m['descricao'] or ''}")
                    st.progress(p, text=f"{brl(feito)} de {brl(m['valor'])} ({p * 100:.0f}%) — ritmo atual: {brl(ritmo)}/ano")
                else:
                    anos = int(m["anos"] or 1)
                    p = min(1.0, patrimonio / m["valor"]) if m["valor"] else 0
                    ini = pd.to_datetime(m["data_inicio"]).date()
                    fim = ini.replace(year=ini.year + anos)
                    meses_rest = max(1, (fim.year - date.today().year) * 12 + (fim.month - date.today().month))
                    taxa_m = ((1 + db.get_config_float("cdi_anual_manual", 10.65) / 100) ** (1 / 12) - 1)
                    # aporte mensal necessário (juros compostos sobre o patrimônio atual)
                    fv_atual = patrimonio * (1 + taxa_m) ** meses_rest
                    falta = max(0.0, m["valor"] - fv_atual)
                    fator = ((1 + taxa_m) ** meses_rest - 1) / taxa_m if taxa_m else meses_rest
                    aporte_nec = falta / fator if fator else falta
                    st.markdown(f"**Patrimônio em {anos} anos** (até {fim:%m/%Y}) · {m['descricao'] or ''}")
                    st.progress(p, text=f"{brl(patrimonio)} de {brl(m['valor'])} ({p * 100:.0f}%)")
                    st.caption(f"Faltam {meses_rest} meses. Ao CDI atual, precisa aportar cerca de "
                               f"**{brl(aporte_nec)}/mês** para chegar lá.")
                if st.button("Remover", key=f"del_meta_{m['id']}"):
                    db.del_meta(int(m["id"])); st.rerun()
