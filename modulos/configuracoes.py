"""Configurações: gastos fixos, categorias, cartões, tipos de crédito, parâmetros, usuários."""
import streamlit as st

import db
import mercado
from utils import brl


def render():
    st.title("⚙️ Configurações")
    abas = st.tabs(["🏠 Gastos fixos", "🏷 Categorias", "💳 Cartões", "💵 Tipos de crédito",
                    "📡 Cotações", "📐 Parâmetros", "👤 Usuários"])
    with abas[0]:
        _fixos()
    with abas[1]:
        _categorias()
    with abas[2]:
        _cartoes()
    with abas[3]:
        _tipos_credito()
    with abas[4]:
        _cotacoes()
    with abas[5]:
        _parametros()
    with abas[6]:
        _usuarios()


def _cotacoes():
    st.caption("Escolha o que aparece no painel de mercado do dashboard. "
               "Índices e moedas vêm do Banco Central; criptomoedas do CoinGecko.")
    ind_atual = [x for x in (db.get_config("painel_indices", "") or "").split(",") if x]
    moe_atual = [x for x in (db.get_config("painel_moedas", "") or "").split(",") if x]
    cri_atual = [x for x in (db.get_config("painel_criptos", "") or "").split(",") if x]
    with st.form("cfg_cotacoes"):
        ind = st.multiselect("Taxas e índices", list(mercado.INDICES_DISPONIVEIS),
                             default=[i for i in ind_atual if i in mercado.INDICES_DISPONIVEIS],
                             format_func=lambda k: mercado.INDICES_DISPONIVEIS[k])
        moe = st.multiselect("Moedas", list(mercado.MOEDAS_DISPONIVEIS),
                             default=[m for m in moe_atual if m in mercado.MOEDAS_DISPONIVEIS],
                             format_func=lambda k: mercado.MOEDAS_DISPONIVEIS[k])
        conhecidas = list(mercado.CRYPTO_IDS)
        cri = st.multiselect("Criptomoedas", conhecidas,
                             default=[c for c in cri_atual if c in conhecidas])
        outras = st.text_input("Outras criptos (id do CoinGecko, separados por vírgula)",
                               value=",".join(c for c in cri_atual if c not in conhecidas),
                               placeholder="ex.: avalanche-2, chainlink")
        if st.form_submit_button("Salvar painel", type="primary"):
            extras = [x.strip() for x in outras.split(",") if x.strip()]
            db.set_config("painel_indices", ",".join(ind))
            db.set_config("painel_moedas", ",".join(moe))
            db.set_config("painel_criptos", ",".join(cri + extras))
            st.success("Painel salvo. O dashboard já mostra a nova seleção.")
    st.markdown("**Conexão com as fontes**")
    c1, c2 = st.columns([1, 3])
    if c1.button("🔄 Testar agora", key="cfg_testar_cot"):
        mercado.resetar_falha()
        try:
            v, d = mercado._sgs(mercado.SGS["selic_efetiva"])
            vm, dm = mercado._sgs(mercado.SGS["selic"])
            c2.success(f"Banco Central respondeu: Selic efetiva {v:.2f}% a.a. ({d}) · meta {vm:.2f}% (desde {dm}).")
        except Exception as e:
            c2.error(f"Banco Central não respondeu: {type(e).__name__}: {str(e)[:200]}")
        try:
            v, o = mercado.cotacao_cripto("BTC")
            c2.info(f"CoinGecko: BTC {brl(v) if v else '—'} ({o}).")
        except Exception as e:
            c2.error(f"CoinGecko não respondeu: {e}")
    erro = mercado.ultimo_erro()
    if erro:
        st.caption(f"Última falha de rede registrada: {erro}. Depois de uma falha o sistema espera 10 min "
                   "antes de tentar de novo — o botão acima força a tentativa.")

    with st.expander("Como conferir os números", expanded=False):
        st.markdown("""
- **Selic efetiva** (série 1178 do BCB) é a taxa *realizada* no dia, normalmente 0,10 ponto abaixo da **meta**
  do Copom (série 432). Use a efetiva para comparar rendimento; a meta é só referência.
- **CDI (% a.a.)** é a série 4389. **CDI do mês** para o mês corrente é a CDI diária (série 12) acumulada do dia 1
  até a última data disponível — a legenda diz quantos dias úteis entraram. Conferência rápida:
  `CDI diária ≈ (1 + CDI a.a.)^(1/252) − 1`; com CDI de 13,90% a.a. dá ≈ 0,0517% ao dia, ou seja, 8 dias úteis ≈ 0,41%.
- Para meses fechados o CDI do mês vem da série 4391 (acumulado oficial).
""")

    st.markdown("**Prévia**")
    itens = mercado.painel_mercado()
    if not itens:
        st.info("Nada selecionado.")
    else:
        cols = st.columns(max(1, min(6, len(itens))))
        for i, it in enumerate(itens):
            v = it["valor"]
            txt = "—" if v is None else (f"{v:.2f}%".replace(".", ",") if it["fmt"].startswith("pct") else brl(v))
            cols[i % len(cols)].metric(it["nome"], txt, help=it["origem"])


def _fixos():
    st.caption("Os fixos aparecem todo mês na aba Gastos com o valor previsto; você ajusta e marca como pago. "
               "Edite direto na tabela (nome, valor previsto, **dia de vencimento**, ativo) e clique em Salvar.")
    with st.form("cfg_fixo", clear_on_submit=True):
        a, b, c, d = st.columns([2, 1, 1, 1])
        nome = a.text_input("Nova conta fixa")
        val = b.number_input("Valor previsto", min_value=0.0, step=10.0, format="%.2f")
        dia = c.number_input("Dia de vencimento", min_value=1, max_value=31, value=10)
        if d.form_submit_button("Adicionar", width="stretch") and nome.strip():
            db.add_fixo_tipo(nome, val, int(dia)); st.rerun()

    df = db.fixos_tipos(ativos=False)
    if df.empty:
        st.info("Nenhuma conta fixa cadastrada.")
        return
    ed = st.data_editor(
        df[["id", "nome", "valor_previsto", "dia_vencimento", "ativo"]].assign(ativo=lambda d: d["ativo"] == 1),
        hide_index=True, width="stretch", key="editor_fixos",
        column_config={
            "id": None,
            "nome": st.column_config.TextColumn("Conta", required=True),
            "valor_previsto": st.column_config.NumberColumn("Valor previsto", format="R$ %.2f", min_value=0.0, step=10.0),
            "dia_vencimento": st.column_config.NumberColumn("Dia de vencimento", min_value=1, max_value=31, step=1),
            "ativo": st.column_config.CheckboxColumn("Ativo"),
        },
        num_rows="fixed")
    if st.button("💾 Salvar alterações", type="primary", key="salvar_fixos_cfg"):
        n = 0
        for _, r in ed.iterrows():
            db.atualizar_fixo_tipo(r["id"], r["nome"], r["valor_previsto"], r["dia_vencimento"], r["ativo"])
            n += 1
        st.success(f"{n} conta(s) atualizada(s).")
        st.rerun()


def _categorias():
    st.caption("Modalidade = grupo (Alimentação/Lazer, Despesa Casa...). Categoria = o detalhe dentro dela.")
    cats = db.categorias(ativas=False)
    with st.form("cfg_cat", clear_on_submit=True):
        a, b, c = st.columns([1.4, 1.4, 0.8])
        grupos = sorted(cats["grupo"].unique().tolist()) if not cats.empty else []
        grupo = a.selectbox("Modalidade existente", grupos + ["+ nova modalidade"])
        novo_grupo = a.text_input("Nova modalidade (se escolheu '+ nova')")
        nome = b.text_input("Categoria")
        if c.form_submit_button("Adicionar", width="stretch") and nome.strip():
            g = novo_grupo.strip() if grupo == "+ nova modalidade" else grupo
            if g:
                db.add_categoria(g, nome); st.rerun()
    for g, sub in cats.groupby("grupo"):
        with st.expander(f"{g} ({int(sub['ativo'].sum())} ativas)", expanded=False):
            for _, x in sub.iterrows():
                a, b = st.columns([4, 1])
                a.markdown(("~~" if not x["ativo"] else "") + x["nome"] + ("~~" if not x["ativo"] else ""))
                if b.button("Desativar" if x["ativo"] else "Reativar", key=f"cat_at_{x['id']}"):
                    db.set_categoria_ativa(int(x["id"]), not x["ativo"]); st.rerun()


def _cartoes():
    st.caption("Compra depois do dia de fechamento cai na fatura do mês seguinte. Parcelas seguem nas faturas seguintes.")
    with st.form("cfg_cartao", clear_on_submit=True):
        a, b, c, d, e, f = st.columns([1.6, 1, 0.8, 0.8, 1, 0.8])
        nome = a.text_input("Nome", placeholder="Nubank, Itaú...")
        band = b.selectbox("Bandeira", ["Visa", "Mastercard", "Elo", "Amex", "Hipercard", "Outra"])
        fech = c.number_input("Fecha dia", 1, 31, 25)
        venc = d.number_input("Vence dia", 1, 31, 5)
        lim = e.number_input("Limite", min_value=0.0, step=500.0, format="%.2f")
        if f.form_submit_button("Salvar", width="stretch") and nome.strip():
            db.add_cartao(nome, band, int(fech), int(venc), lim); st.rerun()
    for _, x in db.cartoes(ativos=False).iterrows():
        a, b, c = st.columns([2.5, 2, 1])
        a.markdown(("~~" if not x["ativo"] else "") + f"**{x['nome']}** · {x['bandeira']}" + ("~~" if not x["ativo"] else ""))
        b.markdown(f"fecha {int(x['dia_fechamento'])} · vence {int(x['dia_vencimento'])} · limite {brl(x['limite'])}")
        if c.button("Desativar" if x["ativo"] else "Reativar", key=f"ca_at_{x['id']}"):
            db.set_cartao_ativo(int(x["id"]), not x["ativo"]); st.rerun()


def _tipos_credito():
    with st.form("cfg_tc", clear_on_submit=True):
        a, b = st.columns([3, 1])
        nome = a.text_input("Novo tipo de crédito")
        if b.form_submit_button("Adicionar", width="stretch") and nome.strip():
            db.execute("INSERT OR IGNORE INTO tipos_credito (nome) VALUES (?)", (nome.strip(),)); st.rerun()
    for _, x in db.tipos_credito(ativos=False).iterrows():
        a, b = st.columns([4, 1])
        a.markdown(("~~" if not x["ativo"] else "") + x["nome"] + ("~~" if not x["ativo"] else ""))
        if b.button("Desativar" if x["ativo"] else "Reativar", key=f"tc_at_{x['id']}"):
            db.execute("UPDATE tipos_credito SET ativo=? WHERE id=?", (int(not x["ativo"]), int(x["id"]))); st.rerun()


def _parametros():
    st.caption("Valores de referência. Selic, CDI, dólar, euro e cripto são buscados na internet "
               "(Banco Central / CoinGecko); os campos manuais valem quando não houver conexão.")
    campos = [
        ("selic_manual", "Selic manual (% a.a.)"),
        ("cdi_anual_manual", "CDI anual manual (% a.a.)"),
        ("poupanca_mensal_manual", "Poupança mensal manual (% a.m.)"),
        ("usd_manual", "Dólar manual (R$)"), ("eur_manual", "Euro manual (R$)"),
        ("limite_baixo_rendimento", "Baixo rendimento: abaixo de X% do CDI"),
        ("limite_oportunidade", "Destaque: acima de X% do CDI"),
        ("meta_taxa_poupanca", "Meta de sobra da renda (%)"),
        ("alerta_cartao_pct_renda", "Alerta: cartão acima de X% da renda"),
    ]
    with st.form("cfg_param"):
        vals = {}
        cols = st.columns(2)
        for i, (k, rot) in enumerate(campos):
            vals[k] = cols[i % 2].number_input(rot, value=db.get_config_float(k, 0), step=0.05, format="%.2f")
        if st.form_submit_button("Salvar parâmetros", type="primary"):
            for k, v in vals.items():
                db.set_config(k, v)
            st.success("Parâmetros salvos.")


def _usuarios():
    u = st.session_state.get("usuario", {})
    st.subheader("Trocar minha senha")
    with st.form("troca_senha", clear_on_submit=True):
        s1 = st.text_input("Nova senha", type="password")
        s2 = st.text_input("Confirmar", type="password")
        if st.form_submit_button("Trocar"):
            if s1 and s1 == s2:
                db.trocar_senha(u["id"], s1); st.success("Senha alterada.")
            else:
                st.error("As senhas não conferem.")
    if u.get("admin"):
        st.subheader("Novo usuário")
        with st.form("novo_usuario", clear_on_submit=True):
            a, b, c, d = st.columns([1.2, 1.2, 1.2, 0.8])
            nome = a.text_input("Nome")
            login = b.text_input("Usuário")
            senha = c.text_input("Senha", type="password")
            if d.form_submit_button("Criar", width="stretch"):
                if nome and login and senha:
                    try:
                        db.criar_usuario(login, nome, senha); st.success("Usuário criado.")
                    except Exception as e:
                        st.error(f"Não foi possível criar: {e}")
        st.dataframe(db.query("SELECT usuario, nome, admin, criado_em FROM usuarios ORDER BY id"),
                     hide_index=True, width="stretch")
