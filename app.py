import math
import os

import pandas as pd
import streamlit as st

APP_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="Asta Fantacalcio 2026/27", page_icon="⚽", layout="wide")

RUOLI = ["P", "D", "C", "A"]
RUOLO_NOME = {"P": "Portiere", "D": "Difensore", "C": "Centrocampista", "A": "Attaccante"}
DEFAULT_SLOT = {"P": 3, "D": 8, "C": 8, "A": 6}

# Curva di prezzo di mercato: prezzo_atteso = quotazione ^ gamma_ruolo, calibrata sui prezzi
# reali osservati nella tua lega (Malen/L.Martinez=300, attaccanti forti 250-300, centro forti 100-150)
# per un'asta da 1000 crediti. Portiere/Difensore non avevano un riferimento reale: sono una stima
# prudente (curva simile, prezzo top più basso, coerente con come di solito vanno in asta) — tarabili qui sotto.
BUDGET_RIFERIMENTO_CURVA = 1000
PREZZO_TOP_DEFAULT = {"A": 300, "C": 150, "D": 130, "P": 70}
PARTITE_STAGIONE = 38  # lunghezza campionato Serie A, per stimare la % di presenze


def valuta_titolarita(partite):
    if pd.isna(partite):
        return {"cat": "ignoto", "icon": "⚪", "label": "Dato non disponibile (nuovo acquisto/debuttante)", "affidabilita": None}
    if partite >= 25:
        return {"cat": "titolare", "icon": "🟢", "label": "Titolare fisso", "affidabilita": 1.0}
    if partite >= 15:
        return {"cat": "rotazione", "icon": "🟡", "label": "Titolare / rotazione", "affidabilita": 0.85}
    if partite >= 5:
        return {"cat": "panchina", "icon": "🟠", "label": "Panchina, poco impiegato", "affidabilita": 0.55}
    return {"cat": "marginale", "icon": "🔴", "label": "Quasi mai in campo", "affidabilita": 0.3}


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

    # affidabilità della fantamedia in base a quanto ha giocato (poche partite = campione rumoroso)
    df["affidabilita"] = df["partite"].apply(lambda p: valuta_titolarita(p)["affidabilita"])
    df["qualita_score"] = df["fantamedia"] * df["affidabilita"].fillna(1.0)

    # percentile di prezzo (quotazione) e di qualità dentro al proprio ruolo: la base del giudizio
    # di convenienza (paga quanto vale? di più? di meno? rispetto ai pari ruolo)
    df["quotazione_percentile_ruolo"] = df.groupby("ruolo")["quotazione"].rank(pct=True) * 100
    df["qualita_percentile_ruolo"] = df.groupby("ruolo")["qualita_score"].rank(pct=True) * 100

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
    titolarita = valuta_titolarita(player["partite"])

    # 1) prezzo di mercato atteso: curva calibrata sui prezzi reali della tua lega
    fattore_budget_utente = budget_totale / BUDGET_RIFERIMENTO_CURVA
    prezzo_mercato = (quotazione ** gamma_ruolo[ruolo]) * fattore_budget_utente

    # 2) aggiustamento leggero in base al rendimento reale rispetto alla media del ruolo, smorzato
    # se il giocatore ha giocato poco (una fantamedia alta su 5 partite è rumore, non segnale)
    media_fm = media_fantamedia_ruolo.get(ruolo, float("nan"))
    if pd.notna(player["fantamedia"]) and pd.notna(media_fm) and media_fm > 0:
        scarto = (player["fantamedia"] - media_fm) / media_fm
        affidabilita = titolarita["affidabilita"] if titolarita["affidabilita"] is not None else 1.0
        fattore_fm = min(1.25, max(0.8, 1 + scarto * affidabilita * 0.6))
    else:
        fattore_fm = 1.0
    prezzo_atteso = prezzo_mercato * fattore_fm
    prezzo_suggerito = int(round(max(1, prezzo_atteso)))

    # 3) convenienza reale: confronta il "rango" di prezzo e il "rango" di qualità del giocatore
    # dentro al suo ruolo. Prezzo alto NON è di per sé un problema (i big costano); il problema è
    # pagare un prezzo da fuoriclasse per un rendimento da comprimario, o viceversa.
    prezzo_pct = player["quotazione_percentile_ruolo"]
    qualita_pct = player["qualita_percentile_ruolo"]
    divario = (qualita_pct - prezzo_pct) if pd.notna(qualita_pct) else None

    # vincolo reale dell'asta: dopo aver preso questo giocatore devi comunque poter chiudere
    # tutti gli altri slot liberi, e in un'asta random il minimo per ogni slot è 1 credito.
    altri_slot_da_riempire = max(0, slot_liberi_totali - 1)
    margine_dopo_acquisto = crediti_residui - prezzo_atteso - altri_slot_da_riempire

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
    elif margine_dopo_acquisto < 0:
        esito = "RISCHIO — PROSCIUGHI IL BUDGET"
        colore = "warning"
        dettaglio = (
            f"Te lo puoi permettere, ma pagarlo ~{prezzo_suggerito} cr. ti lascerebbe sotto il minimo "
            f"per completare gli altri {altri_slot_da_riempire} slot liberi (mancherebbero **{-round(margine_dopo_acquisto)} crediti**). "
            "Fattibile solo se sai già che gli altri slot ti costeranno pochissimo."
        )
    elif titolarita["cat"] in ("panchina", "marginale") and prezzo_suggerito > 5:
        esito = "DUBBIO — RISCHIO PANCHINA"
        colore = "warning"
        presenze = int(player["partite"])
        dettaglio = (
            f"{titolarita['icon']} {titolarita['label']} nella scorsa stagione (**{presenze}/{PARTITE_STAGIONE} presenze**). "
            f"Il prezzo di mercato atteso è ~{prezzo_suggerito} crediti, ma se gioca poco anche quest'anno non li ripaga. "
            "Prendilo solo se hai un motivo concreto per pensare che avrà più spazio (titolare designato, rivale infortunato, nuovo allenatore) — "
            "altrimenti abbassa parecchio l'offerta o lascialo perdere."
        )
    elif divario is None:
        esito = "DATI INSUFFICIENTI"
        colore = "info"
        dettaglio = (
            f"Prezzo di mercato atteso ~{prezzo_suggerito} cr., ma non ho statistiche 2025/26 per lui (nuovo acquisto/debuttante): "
            "non posso dirti se conviene. Valuta tu quanto spazio avrà nella nuova squadra prima di spingerti."
        )
    elif divario >= 25:
        esito = "OTTIMO AFFARE"
        colore = "success"
        dettaglio = (
            f"Rende molto più di quanto costa: è nel **{round(qualita_pct)}° percentile di qualità** ma solo nel "
            f"**{round(prezzo_pct)}° di prezzo** tra i {RUOLO_NOME[ruolo].lower()}i. Vale la pena spingersi anche oltre "
            f"i ~{prezzo_suggerito} cr. attesi, pur di portarlo a casa."
        )
    elif divario >= 10:
        esito = "BUON AFFARE"
        colore = "success"
        dettaglio = (
            f"Buon rapporto qualità/prezzo (percentile qualità {round(qualita_pct)} vs percentile prezzo {round(prezzo_pct)} nel ruolo). "
            f"Prendilo fino a ~{prezzo_suggerito} cr."
        )
    elif divario <= -25:
        esito = "SOPRAVVALUTATO"
        colore = "error"
        dettaglio = (
            f"Costa da fuoriclasse ma rende da comprimario: percentile prezzo {round(prezzo_pct)} contro solo "
            f"{round(qualita_pct)} di qualità nel ruolo. A parità di crediti ci sono alternative decisamente migliori: lascialo perdere."
        )
    elif divario <= -10:
        esito = "SOPRAPPREZZO"
        colore = "warning"
        dettaglio = (
            f"Paghi più di quanto renda rispetto ai pari ruolo (percentile prezzo {round(prezzo_pct)} vs qualità {round(qualita_pct)}). "
            f"Non oltre ~{prezzo_suggerito} cr., e solo se ti serve proprio quel profilo."
        )
    else:
        esito = "PREZZO GIUSTO"
        colore = "info"
        dettaglio = (
            f"Prezzo coerente col rendimento (percentile qualità {round(qualita_pct)} vs prezzo {round(prezzo_pct)}). "
            f"Né affare né fregatura: prendilo a ~{prezzo_suggerito} cr. se ti serve quel ruolo, senza strapparlo a tutti i costi."
        )

    occasione = divario is not None and divario >= 35 and titolarita["cat"] in ("titolare", "rotazione")

    return {
        "esito": esito, "colore": colore, "dettaglio": dettaglio,
        "prezzo_mercato": round(prezzo_mercato), "prezzo_suggerito": prezzo_suggerito,
        "occasione": occasione, "titolarita": titolarita,
        "prezzo_percentile": prezzo_pct, "qualita_percentile": qualita_pct,
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
        tit = consiglio["titolarita"]
        presenze_str = f"{int(player['partite'])}/{PARTITE_STAGIONE} presenze 2025/26" if pd.notna(player["partite"]) else "nessun dato presenze"
        st.subheader(f"{player['nome']} — {player['squadra']} ({RUOLO_NOME[player['ruolo']]})")
        st.markdown(f"{tit['icon']} **{tit['label']}** · {presenze_str}")

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Quotazione uff.", f"{player['quotazione']:.0f}")
        m2.metric("💰 Prezzo mercato atteso", f"~{consiglio['prezzo_mercato']} cr.")
        m3.metric("Fantamedia '25/26", f"{player['fantamedia']:.2f}" if pd.notna(player["fantamedia"]) else "n/d")
        m4.metric("Gol", f"{player['gol']:.0f}" if pd.notna(player["gol"]) else "n/d")
        m5.metric("Assist", f"{player['assist']:.0f}" if pd.notna(player["assist"]) else "n/d")
        m6.metric("FVM", f"{player['fvm']:.0f}" if pd.notna(player["fvm"]) else "n/d")
        st.caption(
            "Il **prezzo di mercato atteso** è quanto probabilmente costerà questo giocatore in un'asta da 1000 "
            "crediti come la tua, in base alla curva calibrata sui prezzi reali e smorzata dalla titolarità. "
            "Il consiglio sotto lo confronta con quanto TU puoi permetterti ora — e con quanto rischia di stare in panchina."
        )

        if pd.isna(player["fantamedia"]):
            st.caption("⚠️ Nessuna statistica trovata per la scorsa stagione (probabile nuovo acquisto, debuttante o dato non disponibile). Il consiglio si basa solo sulla quotazione ufficiale.")

        getattr(st, consiglio["colore"])(f"**{consiglio['esito']}** — {consiglio['dettaglio']}")
        if consiglio["occasione"]:
            st.info("💎 Occasione da non perdere: pochi giocatori nel ruolo hanno un rapporto qualità/prezzo così sbilanciato a tuo favore.")

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
