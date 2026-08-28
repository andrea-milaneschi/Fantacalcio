import math
import os

import pandas as pd
import streamlit as st

APP_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="Asta Fantacalcio 2026/27", page_icon="⚽", layout="wide")

RUOLI = ["P", "D", "C", "A"]
RUOLO_NOME = {"P": "Portiere", "D": "Difensore", "C": "Centrocampista", "A": "Attaccante"}
DEFAULT_SLOT = {"P": 3, "D": 8, "C": 8, "A": 6}
DEFAULT_PESO = {"P": 0.06, "D": 0.18, "C": 0.32, "A": 0.44}

# Curva di prezzo di mercato: prezzo_atteso = quotazione ^ gamma_ruolo, calibrata sui prezzi
# reali osservati nella tua lega (Malen/L.Martinez=300, attaccanti forti 250-300, centro forti 100-150)
# per un'asta da 1000 crediti. Portiere/Difensore non avevano un riferimento reale: sono una stima
# prudente (curva simile, prezzo top più basso, coerente con come di solito vanno in asta) — tarabili qui sotto.
BUDGET_RIFERIMENTO_CURVA = 1000
PREZZO_TOP_DEFAULT = {"A": 300, "C": 150, "D": 130, "P": 70}


@st.cache_data
def load_players():
    df = pd.read_csv(os.path.join(APP_DIR, "players.csv"))
    df["fantamedia"] = pd.to_numeric(df["fantamedia"], errors="coerce")
    df["media_voto"] = pd.to_numeric(df["media_voto"], errors="coerce")
    df["gol"] = pd.to_numeric(df["gol"], errors="coerce")
    df["assist"] = pd.to_numeric(df["assist"], errors="coerce")
    df["partite"] = pd.to_numeric(df["partite"], errors="coerce")
    df["quotazione"] = pd.to_numeric(df["quotazione"], errors="coerce").fillna(1)
    df["fvm"] = pd.to_numeric(df["fvm"], errors="coerce")
    df = df[df["ruolo"].isin(RUOLI)].copy()
    df["label"] = df["nome"] + "  ·  " + df["squadra"] + "  (" + df["ruolo"] + ")"
    return df.sort_values("nome").reset_index(drop=True)


players = load_players()
media_fantamedia_ruolo = players.groupby("ruolo")["fantamedia"].mean()
quotazione_max_ruolo = players.groupby("ruolo")["quotazione"].max()

# ---------------- session state ----------------
# le chiavi dei widget (spesi_totali, presi_P/D/C/A) sono l'unica fonte di verità:
# evita di tenere un dict "ombra" che andrebbe disallineato dai widget ad ogni rerun.
if "spesi_totali" not in st.session_state:
    st.session_state.spesi_totali = 0
for _r in RUOLI:
    if f"presi_{_r}" not in st.session_state:
        st.session_state[f"presi_{_r}"] = 0
if "storico" not in st.session_state:
    st.session_state.storico = []  # list of dict: nome, ruolo, squadra, prezzo


def segna_acquistato(nome, ruolo, squadra, prezzo):
    st.session_state.spesi_totali += prezzo
    st.session_state[f"presi_{ruolo}"] += 1
    st.session_state.storico.append(
        {"nome": nome, "ruolo": ruolo, "squadra": squadra, "prezzo": prezzo}
    )


def reset_asta():
    st.session_state.spesi_totali = 0
    for r in RUOLI:
        st.session_state[f"presi_{r}"] = 0
    st.session_state.storico = []


# ---------------- sidebar: stato asta ----------------
st.sidebar.header("📋 Stato asta")

budget_totale = st.sidebar.number_input("Budget totale (crediti)", min_value=1, value=1000, step=10)

with st.sidebar.expander("Composizione rosa", expanded=False):
    slot_tot = {}
    for r in RUOLI:
        slot_tot[r] = st.number_input(f"{RUOLO_NOME[r]} (tot.)", min_value=0, value=DEFAULT_SLOT[r], key=f"tot_{r}")

st.sidebar.number_input(
    "Crediti spesi finora", min_value=0, step=1, key="spesi_totali"
)

st.sidebar.caption("Giocatori già presi per ruolo")
cols = st.sidebar.columns(4)
for i, r in enumerate(RUOLI):
    with cols[i]:
        st.number_input(
            r, min_value=0, max_value=slot_tot[r],
            key=f"presi_{r}", label_visibility="visible",
        )

crediti_residui = budget_totale - st.session_state.spesi_totali
slot_liberi = {r: max(0, slot_tot[r] - st.session_state[f"presi_{r}"]) for r in RUOLI}
slot_liberi_totali = sum(slot_liberi.values())
rosa_totale = sum(slot_tot.values())

st.sidebar.metric("Crediti residui", crediti_residui)
st.sidebar.metric("Slot liberi", f"{slot_liberi_totali} / {rosa_totale}")

with st.sidebar.expander("🎯 Calibrazione prezzi di mercato"):
    st.caption(
        "Quanto costa il giocatore più forte di ciascun ruolo nella tua asta (1000 crediti). "
        "Gli altri prezzi vengono scalati da questo con una curva realistica (i big costano molto più "
        "che proporzionalmente, i gregari pochissimo). Attaccanti e centrocampisti sono tarati sui prezzi "
        "reali che mi hai dato; portiere e difensore sono una stima prudente — correggili se sai qualcosa di più."
    )
    prezzo_top = {}
    for r in RUOLI:
        prezzo_top[r] = st.number_input(
            f"Prezzo top {RUOLO_NOME[r].lower()} (quot. {quotazione_max_ruolo.get(r, 0):.0f})",
            min_value=1, value=PREZZO_TOP_DEFAULT[r], step=5, key=f"prezzo_top_{r}",
        )

with st.sidebar.expander("⚙️ Impostazioni avanzate"):
    st.caption("Quanto peso economico dare a ciascun ruolo nel calcolo di quanto puoi permetterti (solo per l'avviso di cautela/rischio).")
    peso = {}
    for r in RUOLI:
        peso[r] = st.slider(f"Peso {RUOLO_NOME[r]}", 0.0, 1.0, DEFAULT_PESO[r], 0.01, key=f"peso_{r}")

# gamma per ruolo: prezzo(quotazione) = quotazione ^ gamma, tarato in modo che prezzo(quot_max) = prezzo_top
gamma_ruolo = {}
for r in RUOLI:
    q_max = quotazione_max_ruolo.get(r, 1)
    if q_max > 1:
        gamma_ruolo[r] = math.log(prezzo_top[r]) / math.log(q_max)
    else:
        gamma_ruolo[r] = 1.0

if st.session_state.storico:
    with st.sidebar.expander(f"🧾 Storico acquisti ({len(st.session_state.storico)})", expanded=False):
        for acquisto in reversed(st.session_state.storico):
            st.write(f"{acquisto['nome']} ({acquisto['ruolo']}, {acquisto['squadra']}) — {acquisto['prezzo']} cr.")

st.sidebar.button("🔄 Reset asta", on_click=reset_asta)


# ---------------- motore di raccomandazione ----------------
def calcola_consiglio(player):
    ruolo = player["ruolo"]
    quotazione = max(1.0, player["quotazione"])

    # 1) prezzo di mercato atteso: curva calibrata sui prezzi reali della tua lega
    fattore_budget_utente = budget_totale / BUDGET_RIFERIMENTO_CURVA
    prezzo_mercato = (quotazione ** gamma_ruolo[ruolo]) * fattore_budget_utente

    # 2) aggiustamento leggero in base al rendimento reale rispetto alla media del ruolo
    media_fm = media_fantamedia_ruolo.get(ruolo, float("nan"))
    if pd.notna(player["fantamedia"]) and pd.notna(media_fm) and media_fm > 0:
        scarto = (player["fantamedia"] - media_fm) / media_fm
        fattore_fm = min(1.25, max(0.8, 1 + scarto * 0.6))
    else:
        fattore_fm = 1.0
    prezzo_atteso = prezzo_mercato * fattore_fm

    # 3) quanto puoi permetterti TU adesso, dato il ritmo di spesa rispetto agli slot ancora da riempire
    frazione_soldi = crediti_residui / budget_totale if budget_totale > 0 else 0
    frazione_slot = slot_liberi_totali / rosa_totale if rosa_totale > 0 else 1
    ritmo = frazione_soldi / frazione_slot if frazione_slot > 0 else 1
    fattore_ritmo = min(1.3, max(0.75, ritmo))

    # quanto budget "ti spetterebbe" in media per uno slot di questo ruolo, dati gli slot liberi
    peso_pesato = {r: slot_liberi[r] * peso[r] for r in RUOLI}
    somma_pesi = sum(peso_pesato.values())
    quota_ruolo = crediti_residui * peso_pesato[ruolo] / somma_pesi if somma_pesi > 0 else 0
    budget_medio_slot_ruolo = quota_ruolo / slot_liberi[ruolo] if slot_liberi[ruolo] > 0 else 0

    prezzo_suggerito = int(round(max(1, min(prezzo_atteso * fattore_ritmo, max(crediti_residui, 0)))))

    if slot_liberi[ruolo] == 0:
        esito = "RUOLO COMPLETO"
        colore = "warning"
        dettaglio = f"Hai già preso tutti i {RUOLO_NOME[ruolo].lower()}i previsti: non ti serve, anche se costasse poco."
    elif crediti_residui <= 1:
        esito = "BUDGET ESAURITO"
        colore = "error"
        dettaglio = "Crediti residui insufficienti per offrire con margine."
    elif prezzo_atteso > crediti_residui:
        esito = "FUORI PORTATA"
        colore = "error"
        dettaglio = f"Il prezzo di mercato atteso (~{round(prezzo_atteso)} cr.) supera i tuoi crediti residui ({crediti_residui}). Non rincorrerlo."
    else:
        rapporto = prezzo_atteso / budget_medio_slot_ruolo if budget_medio_slot_ruolo > 0 else 1
        if rapporto <= 1.2:
            esito = "PRENDILO"
            colore = "success"
            dettaglio = f"Prezzo sostenibile per il budget che hai sul ruolo. Preparati a offrire fino a **{prezzo_suggerito} crediti**."
        elif rapporto <= 1.8:
            esito = "VALUTA CON CAUTELA"
            colore = "warning"
            dettaglio = f"Costerà più della media che ti puoi permettere per il ruolo. Spingiti al massimo fino a **{prezzo_suggerito} crediti**, solo se lo vuoi davvero e sei disposto a tagliare altrove."
        else:
            esito = "EVITA / RISCHIO SBILANCIARE"
            colore = "error"
            dettaglio = f"Prezzo atteso troppo alto rispetto al budget rimasto per il ruolo ({round(budget_medio_slot_ruolo)} cr. medi/slot). Rischi di non chiudere la rosa."

    occasione = pd.notna(player["fantamedia"]) and fattore_fm >= 1.15 and prezzo_mercato <= budget_totale * 0.05

    return {
        "esito": esito, "colore": colore, "dettaglio": dettaglio,
        "prezzo_mercato": round(prezzo_mercato), "prezzo_suggerito": prezzo_suggerito,
        "budget_medio_slot_ruolo": round(budget_medio_slot_ruolo), "occasione": occasione,
    }


# ---------------- UI principale ----------------
st.title("⚽ Asta Fantacalcio 2026/27")
st.caption(
    "Quotazioni ufficiali 2026/27 + statistiche reali stagione 2025/26 (fantamedia, media voto, gol, assist). "
    "Scrivi un nome per avere subito un consiglio su prezzo e convenienza."
)

nome_cercato = st.selectbox(
    "Cerca un giocatore",
    options=players["label"].tolist(),
    index=None,
    placeholder="Scrivi il nome del giocatore...",
)

if nome_cercato:
    player = players[players["label"] == nome_cercato].iloc[0]
    consiglio = calcola_consiglio(player)

    c1, c2 = st.columns([2, 1])

    with c1:
        st.subheader(f"{player['nome']} — {player['squadra']} ({RUOLO_NOME[player['ruolo']]})")

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Quotazione uff.", f"{player['quotazione']:.0f}")
        m2.metric("💰 Prezzo mercato atteso", f"~{consiglio['prezzo_mercato']} cr.")
        m3.metric("Fantamedia '25/26", f"{player['fantamedia']:.2f}" if pd.notna(player["fantamedia"]) else "n/d")
        m4.metric("Gol", f"{player['gol']:.0f}" if pd.notna(player["gol"]) else "n/d")
        m5.metric("Assist", f"{player['assist']:.0f}" if pd.notna(player["assist"]) else "n/d")
        m6.metric("FVM", f"{player['fvm']:.0f}" if pd.notna(player["fvm"]) else "n/d")
        st.caption("Il **prezzo di mercato atteso** è quanto probabilmente costerà questo giocatore in un'asta da 1000 crediti come la tua, in base alla curva calibrata sui prezzi reali. Il consiglio sotto lo confronta con quanto TU puoi permetterti ora.")

        if pd.isna(player["fantamedia"]):
            st.caption("⚠️ Nessuna statistica trovata per la scorsa stagione (probabile nuovo acquisto, debuttante o dato non disponibile). Il consiglio si basa solo sulla quotazione ufficiale.")

        getattr(st, consiglio["colore"])(f"**{consiglio['esito']}** — {consiglio['dettaglio']}")
        if consiglio["occasione"]:
            st.info("💎 Possibile occasione: rendimento nettamente sopra la media del ruolo per una quotazione bassa.")

    with c2:
        st.markdown("**Segna l'acquisto**")
        prezzo_pagato = st.number_input(
            "Prezzo pagato (crediti)", min_value=0, value=consiglio["prezzo_suggerito"], step=1, key="prezzo_input"
        )
        if slot_liberi[player["ruolo"]] == 0:
            st.button("Segna come preso", disabled=True, help="Ruolo già completo")
        else:
            st.button(
                "✅ Segna come preso (mio)",
                on_click=segna_acquistato,
                args=(player["nome"], player["ruolo"], player["squadra"], prezzo_pagato),
            )

    if pd.notna(player["fantamedia"]):
        media_ruolo = media_fantamedia_ruolo.get(player["ruolo"])
        confronto = pd.DataFrame(
            {"Fantamedia": [player["fantamedia"], media_ruolo]},
            index=[player["nome"], f"Media {RUOLO_NOME[player['ruolo']]}i"],
        )
        st.bar_chart(confronto)

st.divider()

with st.expander("📊 Top disponibili per ruolo (riferimento rapido)"):
    tabs = st.tabs([RUOLO_NOME[r] for r in RUOLI])
    for tab, r in zip(tabs, RUOLI):
        with tab:
            top = players[players["ruolo"] == r].sort_values("quotazione", ascending=False).head(20)
            st.dataframe(
                top[["nome", "squadra", "quotazione", "fantamedia", "gol", "assist"]].rename(
                    columns={"nome": "Nome", "squadra": "Squadra", "quotazione": "Quot.",
                             "fantamedia": "Fantamedia", "gol": "Gol", "assist": "Assist"}
                ),
                hide_index=True, width="stretch",
            )
