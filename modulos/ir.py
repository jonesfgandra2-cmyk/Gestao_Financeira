"""Imposto de Renda: importar informes, revisar fichas, apurar e exportar."""
from datetime import date

import pandas as pd
import streamlit as st

import db
import ir_core as irc
from utils import STATUS, badge, brl, kpi, pct


def render():
    irc.iniciar()
    st.title("🧾 Imposto de Renda")
    anos = sorted(set(irc.anos_com_dados()) | {date.today().year - 1, date.today().year}, reverse=True)
    c1, c2 = st.columns([1, 3])
    with c1:
        _padrao = date.today().year - 1
        ano = st.selectbox("Ano-calendário", anos, key="ir_ano",
                           index=anos.index(_padrao) if _padrao in anos else 0,
                           help="Ano em que você recebeu/pagou. A declaração é entregue no ano seguinte.")
    with c2:
        st.caption(f"Declaração **DIRPF {ano + 1}** (ano-calendário {ano}). Importe os informes, revise as fichas e "
                   "veja a prévia do imposto. Depois é só digitar no programa da Receita seguindo o roteiro.")

    ap = irc.apurar(ano)
    k = st.columns(5)
    with k[0]:
        kpi("Rendimentos tributáveis", brl(ap["tributaveis"]), f"isentos {brl(ap['isentos'], 0)} · exclusiva {brl(ap['exclusiva'], 0)}")
    with k[1]:
        kpi("Deduções (completa)", brl(ap["deducoes"]), f"simplificado {brl(ap['desconto_simplificado'], 0)}")
    with k[2]:
        kpi("Imposto devido", brl(ap["imposto"]), f"melhor: {ap['melhor']} · alíq. efetiva {pct(ap['aliquota_efetiva'])}")
    with k[3]:
        kpi("IR retido na fonte", brl(ap["irrf"]), "informado pelas fontes")
    with k[4]:
        s = ap["saldo"]
        kpi("A restituir" if s < 0 else "A pagar", brl(abs(s)), "prévia — confira no programa",
            STATUS["bom"] if s < 0 else (STATUS["critico"] if s > 0 else "#0b0b0b"))

    abas = st.tabs(["📥 Importar informes", "📋 Fichas", "🧮 Apuração", "📐 Tabela do ano", "📤 Roteiro / exportar"])
    with abas[0]:
        _importar(ano)
    with abas[1]:
        _fichas(ano)
    with abas[2]:
        _apuracao(ano, ap)
    with abas[3]:
        _tabela(ano)
    with abas[4]:
        _exportar(ano)


# ── Importar informes ───────────────────────────────────────────────────────
def _importar(ano):
    st.markdown("Envie o **PDF** (ou planilha) de cada informe: comprovante de rendimentos do empregador/INSS, "
                "informes de bancos e corretoras, plano de saúde, escola, previdência. O sistema lê o que consegue "
                "e monta os lançamentos **para você conferir** antes de gravar.")
    arq = st.file_uploader("Informe", type=["pdf", "xlsx", "xls", "csv", "txt"], key=f"ir_arq_{ano}")
    col_s, col_t = st.columns([1.2, 2])
    with col_s:
        if st.button("✨ Sugerir lançamentos a partir do que já está no sistema", key=f"ir_sug_{ano}",
                     help="Saldos dos investimentos em 31/12, rendimentos, salário, gastos de saúde/educação."):
            st.session_state[f"ir_cand_{ano}"] = irc.sugestoes_do_sistema(ano)
            st.session_state[f"ir_cand_meta_{ano}"] = {"tipo": "sistema", "fonte": "Sistema", "cnpj": None,
                                                       "arquivo_nome": None, "arquivo": None, "texto": ""}
            st.rerun()
    with col_t:
        st.caption("Os lançamentos sugeridos pelo sistema são estimativas: os valores oficiais são os dos informes. "
                   "Use-os para não esquecer nada e ajuste pelo documento.")

    if arq is not None and st.session_state.get(f"ir_arq_lido_{ano}") != arq.name + str(arq.size):
        dados = arq.getvalue()
        texto = irc.texto_do_arquivo(arq.name, dados)
        tipo = irc.detectar_tipo(texto) if texto else "outro"
        ano_txt = irc._ano_no_texto(texto) if texto else None
        cand = irc.extrair(texto, tipo, ano) if texto else []
        st.session_state[f"ir_cand_{ano}"] = cand
        st.session_state[f"ir_cand_meta_{ano}"] = {"tipo": tipo, "fonte": (cand[0]["fonte"] if cand else None),
                                                   "cnpj": (cand[0]["cnpj_cpf"] if cand else irc._cnpj(texto or "")),
                                                   "arquivo_nome": arq.name, "arquivo": dados, "texto": texto,
                                                   "ano_txt": ano_txt}
        st.session_state[f"ir_arq_lido_{ano}"] = arq.name + str(arq.size)

    cand = st.session_state.get(f"ir_cand_{ano}")
    meta = st.session_state.get(f"ir_cand_meta_{ano}")
    if meta is None:
        _lista_informes(ano)
        return

    st.markdown("---")
    st.markdown("#### Conferir antes de gravar")
    if meta.get("arquivo_nome") and not meta.get("texto"):
        st.warning("Não consegui extrair texto deste arquivo (PDF só com imagem ou protegido). "
                   "O arquivo será guardado; preencha os valores abaixo à mão.")
    if meta.get("ano_txt") and meta["ano_txt"] != ano:
        st.warning(f"O documento parece ser do ano-calendário **{meta['ano_txt']}**, mas você está em **{ano}**. "
                   "Troque o ano no topo se for o caso.")
    a, b, c = st.columns([1.4, 1.6, 1])
    tipo = a.selectbox("Tipo de informe", list(irc.TIPOS_INFORME), key=f"ir_tipo_{ano}",
                       index=list(irc.TIPOS_INFORME).index(meta.get("tipo", "outro")),
                       format_func=lambda k: irc.TIPOS_INFORME[k])
    fonte = b.text_input("Fonte (empresa / banco / operadora)", value=meta.get("fonte") or "", key=f"ir_fonte_{ano}")
    cnpj = c.text_input("CNPJ / CPF", value=meta.get("cnpj") or "", key=f"ir_cnpj_{ano}")
    if tipo != meta.get("tipo") and meta.get("texto"):
        # tipo trocado pelo usuário: reextrai com as regras do novo tipo
        meta["tipo"] = tipo
        cand = irc.extrair(meta["texto"], tipo, ano)
        st.session_state[f"ir_cand_{ano}"] = cand

    opcoes_ficha = list(irc.FICHAS)
    base = pd.DataFrame(cand or [], columns=["ficha", "codigo", "descricao", "valor_ant", "valor", "cnpj_cpf", "fonte"])
    if base.empty:
        base = pd.DataFrame([{"ficha": "tributaveis", "codigo": "PJ", "descricao": "", "valor_ant": 0.0, "valor": 0.0,
                              "cnpj_cpf": cnpj, "fonte": fonte}])
    st.caption("Edite, apague ou acrescente linhas. **Código** segue as fichas do programa da Receita "
               "(veja a aba Fichas para a lista).")
    ed = st.data_editor(
        base[["ficha", "codigo", "descricao", "valor_ant", "valor"]], num_rows="dynamic", hide_index=True,
        width="stretch", key=f"ir_editor_{ano}_{meta.get('arquivo_nome')}",
        column_config={
            "ficha": st.column_config.SelectboxColumn("Ficha", options=opcoes_ficha, required=True,
                                                      format_func=lambda k: irc.FICHAS.get(k, k)),
            "codigo": st.column_config.TextColumn("Código"),
            "descricao": st.column_config.TextColumn("Descrição", required=True, width="large"),
            "valor_ant": st.column_config.NumberColumn(f"Situação 31/12/{ano - 1}", format="R$ %.2f",
                                                       help="Só para Bens e direitos / Dívidas."),
            "valor": st.column_config.NumberColumn(f"Valor (ou 31/12/{ano})", format="R$ %.2f", required=True),
        })
    if meta.get("texto"):
        with st.expander("Texto extraído do documento (para conferir)"):
            st.text(meta["texto"][:6000])

    g1, g2 = st.columns([1, 1])
    if g1.button("💾 Gravar informe e lançamentos", type="primary", key=f"ir_gravar_{ano}"):
        linhas = ed.dropna(subset=["descricao"])
        linhas = linhas[linhas["descricao"].astype(str).str.strip() != ""]
        inf_id = None
        if meta.get("arquivo_nome") or meta.get("tipo") != "sistema":
            inf_id = irc.add_informe(ano, tipo, fonte, cnpj, meta.get("arquivo_nome"), meta.get("arquivo"),
                                     meta.get("texto"), {"linhas": int(len(linhas))})
        for _, r in linhas.iterrows():
            irc.add_lancamento(ano, r["ficha"], r["codigo"], r["descricao"], r["valor"], r["valor_ant"],
                               cnpj or None, fonte or None, informe_id=inf_id)
        for k in (f"ir_cand_{ano}", f"ir_cand_meta_{ano}"):
            st.session_state.pop(k, None)
        st.success(f"{len(linhas)} lançamento(s) gravados em {ano}.")
        st.rerun()
    if g2.button("Descartar", key=f"ir_descartar_{ano}"):
        for k in (f"ir_cand_{ano}", f"ir_cand_meta_{ano}"):
            st.session_state.pop(k, None)
        st.rerun()
    st.markdown("---")
    _lista_informes(ano)


def _lista_informes(ano):
    inf = irc.informes(ano)
    st.markdown(f"#### Informes já importados em {ano} ({len(inf)})")
    if inf.empty:
        st.info("Nenhum informe ainda.")
        return
    for _, r in inf.iterrows():
        a, b, c, d = st.columns([2.2, 2, 1, 0.6])
        a.markdown(f"**{r['fonte'] or '—'}**  \n<span style='font-size:12px;color:#6b6a66'>{irc.TIPOS_INFORME.get(r['tipo'], r['tipo'])}</span>",
                   unsafe_allow_html=True)
        b.caption(f"{r['cnpj'] or ''} · {r['arquivo_nome'] or 'sem arquivo'} · {str(r['criado_em'])[:16]}")
        if r["arquivo_nome"]:
            nome, dados = irc.arquivo_informe(int(r["id"]))
            if dados:
                c.download_button("⬇️", data=bytes(dados), file_name=nome, key=f"ir_dl_{r['id']}", help="Baixar o arquivo")
        if d.button("🗑", key=f"ir_del_inf_{r['id']}", help="Excluir informe e seus lançamentos"):
            irc.del_informe(int(r["id"])); st.rerun()


# ── Fichas ──────────────────────────────────────────────────────────────────
def _fichas(ano):
    ficha = st.radio("Ficha", list(irc.FICHAS), horizontal=True, format_func=lambda k: irc.FICHAS[k], key=f"ir_ficha_{ano}",
                     label_visibility="collapsed")
    codigos = irc.CODIGOS.get(ficha, {})
    with st.expander("Códigos desta ficha", expanded=False):
        st.dataframe(pd.DataFrame([{"Código": k, "Descrição": v} for k, v in codigos.items()]), hide_index=True,
                     width="stretch", height=min(360, 40 + 35 * len(codigos)))

    # novo lançamento manual
    with st.form(f"ir_novo_{ano}_{ficha}", clear_on_submit=True):
        st.markdown("**Novo lançamento manual**")
        a, b, c, d, e = st.columns([1, 2.2, 1.2, 1, 1])
        cod = a.selectbox("Código", list(codigos) or ["—"], format_func=lambda k: f"{k}" if k in codigos else k)
        desc = b.text_input("Descrição / discriminação")
        cnpj = c.text_input("CNPJ/CPF")
        v_ant = d.number_input(f"31/12/{ano - 1}", min_value=0.0, step=100.0, format="%.2f") if ficha in ("bens", "dividas") else 0.0
        val = e.number_input("Valor" if ficha not in ("bens", "dividas") else f"31/12/{ano}", step=100.0, format="%.2f")
        mes = st.selectbox("Mês (renda variável)", list(range(1, 13)), key=f"ir_mes_{ano}") if ficha == "renda_variavel" else None
        if st.form_submit_button("Adicionar", type="primary"):
            if desc.strip():
                irc.add_lancamento(ano, ficha, cod, desc, val, v_ant, cnpj or None, None, mes)
                st.rerun()
            else:
                st.error("Informe a descrição.")

    df = irc.lancamentos(ano, ficha)
    if df.empty:
        st.info("Nada lançado nesta ficha.")
        return
    tot = float(df["valor"].sum())
    st.markdown(f"**{len(df)} lançamento(s)** · total **{brl(tot)}**"
                + (f" · 31/12/{ano - 1}: {brl(df['valor_ant'].sum())}" if ficha in ("bens", "dividas") else ""))
    ed = st.data_editor(
        df[["id", "codigo", "descricao", "cnpj_cpf", "valor_ant", "valor", "fonte", "obs"]],
        hide_index=True, width="stretch", key=f"ir_ed_{ano}_{ficha}", num_rows="fixed",
        column_config={
            "id": None, "codigo": st.column_config.TextColumn("Código", width="small"),
            "descricao": st.column_config.TextColumn("Descrição", width="large"),
            "cnpj_cpf": st.column_config.TextColumn("CNPJ/CPF"),
            "valor_ant": st.column_config.NumberColumn(f"31/12/{ano - 1}", format="R$ %.2f") if ficha in ("bens", "dividas") else None,
            "valor": st.column_config.NumberColumn("Valor" if ficha not in ("bens", "dividas") else f"31/12/{ano}", format="R$ %.2f"),
            "fonte": st.column_config.TextColumn("Fonte", disabled=True),
            "obs": st.column_config.TextColumn("Obs"),
        })
    a, b = st.columns([1, 3])
    if a.button("💾 Salvar edições", key=f"ir_salvar_{ano}_{ficha}"):
        for _, r in ed.iterrows():
            irc.atualizar_lancamento(r["id"], r["codigo"], r["descricao"], r["cnpj_cpf"], r["valor"],
                                     r.get("valor_ant", 0) if ficha in ("bens", "dividas") else 0, r["obs"])
        st.success("Salvo."); st.rerun()
    with b:
        excl = st.multiselect("Excluir lançamentos", df["id"].tolist(), key=f"ir_excl_{ano}_{ficha}",
                              format_func=lambda i: f"#{i} {df.loc[df['id'] == i, 'descricao'].iloc[0][:40]}",
                              label_visibility="collapsed", placeholder="Excluir lançamentos...")
        if excl and st.button(f"Excluir {len(excl)}", key=f"ir_excl_btn_{ano}_{ficha}"):
            for i in excl:
                irc.del_lancamento(int(i))
            st.rerun()


# ── Apuração ────────────────────────────────────────────────────────────────
def _apuracao(ano, ap):
    for nivel, txt in irc.alertas(ano, ap):
        st.markdown(badge(txt, nivel), unsafe_allow_html=True)
    st.markdown("")
    c1, c2 = st.columns(2)
    linhas_c = [("Rendimentos tributáveis", ap["tributaveis"]),
                ("(−) Previdência oficial (INSS)", -ap["inss"]),
                ("(−) PGBL (até 12% dos tributáveis)", -ap["pgbl"]),
                ("(−) Pensão alimentícia", -ap["pensao"]),
                ("(−) Saúde (sem limite)", -ap["saude"]),
                ("(−) Educação (com limite)", -ap["educacao"]),
                (f"(−) Dependentes ({ap['dependentes']})", -ap["ded_dependentes"]),
                ("= Base de cálculo", ap["base_completa"]),
                ("Imposto pela tabela", ap["imposto_completa"] + (ap["reducao_aplicada"] if ap["melhor"] == "completa" else 0)),
                ("(−) Redução renda baixa", -ap["reducao_aplicada"] if ap["tabela"].get("reducao_baixa_renda") else 0),
                ("= Imposto devido (completa)", ap["imposto_completa"])]
    linhas_s = [("Rendimentos tributáveis", ap["tributaveis"]),
                ("(−) Desconto simplificado (20%, limitado)", -ap["desconto_simplificado"]),
                ("= Base de cálculo", ap["base_simplificada"]),
                ("= Imposto devido (simplificada)", ap["imposto_simplificada"])]

    def tabela(titulo, linhas, destaque):
        html = f"<div style='border:1px solid {'#008300' if destaque else '#e3e2de'};border-radius:8px;padding:12px 14px;background:#fff'>"
        html += f"<div style='font-weight:600;margin-bottom:6px'>{titulo}{' ✔ melhor opção' if destaque else ''}</div>"
        html += "<table style='width:100%;font-size:13.5px;border-collapse:collapse'>"
        for rot, v in linhas:
            forte = rot.startswith("=")
            html += (f"<tr><td style='padding:3px 0;{'font-weight:600' if forte else ''}'>{rot}</td>"
                     f"<td style='text-align:right;font-variant-numeric:tabular-nums;{'font-weight:600' if forte else ''}'>{brl(v)}</td></tr>")
        return html + "</table></div>"
    with c1:
        st.markdown(tabela("Declaração completa", linhas_c, ap["melhor"] == "completa"), unsafe_allow_html=True)
    with c2:
        st.markdown(tabela("Declaração simplificada", linhas_s, ap["melhor"] == "simplificada"), unsafe_allow_html=True)
        st.markdown("")
        s = ap["saldo"]
        st.markdown(f"**Imposto devido:** {brl(ap['imposto'])} · **IR já retido:** {brl(ap['irrf'])} → "
                    + (f"<span style='color:#008300;font-weight:600'>restituição de {brl(-s)}</span>" if s < 0
                       else f"<span style='color:#e34948;font-weight:600'>a pagar {brl(s)}</span>"),
                    unsafe_allow_html=True)
        st.caption(f"13º: {brl(ap['exclusiva'])} com IR exclusivo de {brl(ap['ir_13'])} (não entra no ajuste). "
                   f"Patrimônio 31/12: {brl(ap['patrimonio'])} (antes {brl(ap['patrimonio_ant'])}); "
                   f"dívidas {brl(ap['dividas'])}.")
    st.caption("Prévia calculada pela tabela anual configurada na aba **Tabela do ano**. O valor final é o do "
               "programa da Receita — use isto para conferir e para escolher entre completa e simplificada.")


# ── Tabela do ano ───────────────────────────────────────────────────────────
def _tabela(ano):
    t = irc.tabela(ano)
    st.caption(t.get("obs", ""))
    with st.form(f"ir_tab_{ano}"):
        st.markdown("**Faixas anuais** (limite superior, alíquota %, parcela a deduzir)")
        fx = pd.DataFrame(t["faixas"], columns=["limite", "aliquota", "deduzir"])
        fx_ed = st.data_editor(fx, hide_index=True, width="stretch", num_rows="dynamic",
                               column_config={"limite": st.column_config.NumberColumn("Até (R$) — vazio = sem limite", format="%.2f"),
                                              "aliquota": st.column_config.NumberColumn("Alíquota %", format="%.1f"),
                                              "deduzir": st.column_config.NumberColumn("Parcela a deduzir", format="%.2f")})
        a, b, c = st.columns(3)
        dep = a.number_input("Dedução por dependente (ano)", value=float(t["dependente"]), format="%.2f")
        edu = b.number_input("Limite de educação por pessoa", value=float(t["educacao"]), format="%.2f")
        pg = c.number_input("PGBL: % máximo dos tributáveis", value=float(t["pgbl_pct"]), format="%.1f")
        d, e = st.columns(2)
        sp = d.number_input("Desconto simplificado %", value=float(t["simplificado_pct"]), format="%.1f")
        sm = e.number_input("Desconto simplificado: teto (R$)", value=float(t["simplificado_max"]), format="%.2f")
        red = st.checkbox("Aplicar redução para renda baixa (Lei 15.270/2025 — a partir do ano-calendário 2026)",
                          value=bool(t.get("reducao_baixa_renda")))
        r1, r2, r3, r4 = st.columns(4)
        ria = r1.number_input("Isento até (anual)", value=float(t.get("reducao_isento_ate", 60000)), format="%.2f")
        rza = r2.number_input("Redução zera em (anual)", value=float(t.get("reducao_zera_ate", 88200)), format="%.2f")
        ra = r3.number_input("Coeficiente A", value=float(t.get("reducao_a", 11743.44)), format="%.2f")
        rb = r4.number_input("Coeficiente B", value=float(t.get("reducao_b", 0.133145)), format="%.6f")
        if st.form_submit_button("Salvar tabela", type="primary"):
            faixas = []
            for _, r in fx_ed.iterrows():
                lim = None if pd.isna(r["limite"]) else float(r["limite"])
                faixas.append([lim, float(r["aliquota"]), float(r["deduzir"])])
            t.update({"faixas": faixas, "dependente": dep, "educacao": edu, "pgbl_pct": pg, "simplificado_pct": sp,
                      "simplificado_max": sm, "reducao_baixa_renda": red, "reducao_isento_ate": ria,
                      "reducao_zera_ate": rza, "reducao_a": ra, "reducao_b": rb})
            irc.salvar_tabela(ano, t)
            st.success("Tabela salva."); st.rerun()
    if st.button("Restaurar padrão do sistema", key=f"ir_tab_reset_{ano}"):
        db.execute("DELETE FROM config WHERE chave=?", (f"ir_tabela_{ano}",)); st.rerun()


# ── Exportar ────────────────────────────────────────────────────────────────
def _exportar(ano):
    st.markdown("Roteiro para digitar no programa da Receita: uma aba por ficha, com código, descrição, CNPJ e valores, "
                "mais a apuração. Guarde junto com os informes.")
    df = irc.lancamentos(ano)
    if df.empty:
        st.info("Nada para exportar ainda.")
        return
    if st.button("Preparar planilha", key=f"ir_prep_{ano}"):
        st.session_state[f"ir_xlsx_{ano}"] = irc.roteiro_excel(ano)
    if st.session_state.get(f"ir_xlsx_{ano}"):
        st.download_button("⬇️ Baixar roteiro (.xlsx)", st.session_state[f"ir_xlsx_{ano}"],
                           f"roteiro_irpf_{ano + 1}_ano_{ano}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"ir_dl_{ano}")
    st.markdown("#### Resumo por ficha")
    for ficha, rot in irc.FICHAS.items():
        d = df[df["ficha"] == ficha]
        if d.empty:
            continue
        with st.expander(f"{rot} — {len(d)} item(ns) · {brl(d['valor'].sum())}"):
            st.dataframe(d[["codigo", "descricao", "cnpj_cpf", "valor_ant", "valor", "obs"]], hide_index=True, width="stretch")
