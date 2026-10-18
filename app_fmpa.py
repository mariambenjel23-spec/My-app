# -*- coding: utf-8 -*-
# ============================================================================
#  🏥 FMPA VALID — Plateforme de VALIDATION ASYNCHRONE des dossiers d'achats
#  Service des Marchés · Faculté de Médecine et de Pharmacie d'Agadir (FMPA)
# ----------------------------------------------------------------------------
#  CONCEPT : la commission (Professeurs + Médecins très occupés) donne son avis
#  EN DIFFÉRÉ depuis la plateforme, sans réunion physique. La réunion ne reste
#  nécessaire QUE pour les dossiers en désaccord (« avis partagés »).
#
#  🤖 L'IA intervient à 7 endroits (moteur heuristique local, remplaçable par
#     un vrai LLM — voir la note en tête de la section 4) :
#      1) Résumé exécutif      2) Score de conformité /100   3) Anomalies
#      4) Priorisation         5) Justifications suggérées   6) Chatbot + brouillons d'avis
#      7) Génération du PV de séance
#
#  ⚙️  Lancement :  pip install streamlit pandas  →  streamlit run app_fmpa.py
#  👤  Démo     : se connecter avec n'importe quel profil affiché.
#                 La réinitialisation (sidebar) recrée les données de démo.
#  📦  Données  : simulées dans st.session_state (§6) ; §10 = pistes réelles.
#  Version minimale de Streamlit conseillée : ≥ 1.31
# ============================================================================

import io
import re
import time
from datetime import datetime, timedelta, date

import pandas as pd
import streamlit as st

# ============================================================================
# 1) CONFIGURATION DE LA PAGE + STYLE VISUEL
# ============================================================================
st.set_page_config(page_title="FMPA VALID", page_icon="🏥", layout="wide")

st.markdown("""<style>
.block-container {padding-top: 1.1rem;}
.fmp-chip {display:inline-block; padding:2px 10px; margin:0 5px 2px 0;
           border-radius:999px; font-size:.78rem; font-weight:600; color:#26303b;}
.fmp-hero {border-radius:18px; padding:26px 34px; margin-bottom:4px;
           background:linear-gradient(135deg,#0d3b66 0%,#1b6ca8 55%,#2a9d8f 100%);}
.fmp-hero h1 {color:#ffffff; margin-bottom:2px;}
.fmp-hero p {color:#dff1ff; font-size:1.02rem; margin:0;}
</style>""", unsafe_allow_html=True)

ss = st.session_state  # raccourci d'écriture

# ============================================================================
# 2) CONSTANTES MÉTIER
# ============================================================================
SEUIL_SIMPLIFIE = 50_000        # DH : au-delà → consultation restreinte
SEUIL_APPEL_OFFRES = 100_000    # DH : au-delà → appel d'offres ouvert
MN_REUNION_PAR_DECISION = 20    # minutes de réunion économisées par avis
QUORUM = 4                      # nombre de membres de la commission

# --- Personnel (données de démonstration) ------------------------------------
ADMIN = {"id": "AD", "nom": "Mme R. Fadili", "role": "Administrateur",
         "specialite": "Chef du Service des Marchés"}
COMMISSION = [
    {"id": "P1", "nom": "Pr. A. Bennani",  "role": "Membre", "specialite": "Anesthésie-Réanimation · Président"},
    {"id": "P2", "nom": "Pr. S. Chraibi",  "role": "Membre", "specialite": "Pédagogie & Simulation"},
    {"id": "P3", "nom": "Dr. M. Tahiri",   "role": "Membre", "specialite": "Urgences · Polyclinique"},
    {"id": "P4", "nom": "Pr. N. El Fassi", "role": "Membre", "specialite": "Anatomie · Contrôle budgétaire"},
]
UTILISATEURS = [ADMIN, *COMMISSION]

# --- Listes métier ------------------------------------------------------------
SERVICES = ["Département de Médecine", "Département de Pharmacie",
            "Département de Médecine Dentaire", "Laboratoire d'Anatomie",
            "Polyclinique universitaire", "Bibliothèque universitaire",
            "Service Informatique", "Administration générale"]
CATEGORIES = ["Matériel biomédical", "Mannequins pédagogiques",
              "Matériel informatique", "Consommables",
              "Mobilier de bureau", "Ouvrages & documentation"]

# --- Statuts, sens de vote, menus ------------------------------------------------
STATUTS = {
    "En attente":      ("🟠", "#fff3e0"),
    "En cours d'avis": ("🟦", "#e3f2fd"),
    "Validée":         ("✅", "#e8f5e9"),
    "Refusée":         ("⛔", "#ffebee"),
    "Avis partagés":   ("🟪", "#f3e5f5"),
    "Clôturée":        ("⏺️", "#eceff1"),
}
STATUTS_TERMINAUX = ("Validée", "Refusée", "Avis partagés", "Clôturée")
SENS = {"✅ Favorable": "favorable", "⛔ Défavorable": "defavorable",
        "⏸️ Réserver (neutre)": "neutre", "❓ Demande de précision": "precision"}
CODE_VERS_LABEL = {v: k for k, v in SENS.items()}
RANG_PRIORITE = {"🥇": 1, "🥈": 2, "🥉": 3}
MENUS = {
    "Administrateur": ["🏠 Tableau de bord", "📋 Dossiers", "➕ Nouveau dossier",
                       "🤖 Assistant IA", "📄 Rapports & PV"],
    "Membre": ["🏠 Tableau de bord", "📋 Dossiers", "✍️ Mes validations", "🤖 Assistant IA"],
}

# ============================================================================
# 3) PETITES FONCTIONS UTILITAIRES
# ============================================================================
def dh(montant):
    """Format monétaire marocain : 93 600 DH."""
    return f"{montant:,.0f}".replace(",", " ") + " DH"


def chip(texte, couleur):
    """Pastille HTML colorée (utilise la classe CSS .fmp-chip)."""
    return f'<span class="fmp-chip" style="background:{couleur};">{texte}</span>'


def badge_statut(statut):
    ico, cou = STATUTS.get(statut, ("⚪", "#eeeeee"))
    return chip(f"{ico} {statut}", cou)


def badge_priorite(priorite):
    cou = {"🥇": "#ffd6d6", "🥈": "#ffeccf", "🥉": "#e0f2df"}.get((priorite or "🥉")[0], "#e0f2df")
    return chip(priorite, cou)


def extrait(texte, n=110):
    texte = (texte or "").strip()
    return texte if len(texte) <= n else texte[:n - 1] + "…"


def _dossier_par_ref(ref):
    for d in ss.dossiers:
        if d["ref"].upper() == ref.upper():
            return d
    return None


def mettre_a_jour_statut(d):
    """Règle métier : le statut se recalcule après chaque avis (majorité simple)."""
    votes = [x["sens"] for x in d["decisions"]]
    if len(votes) < QUORUM:
        d["statut"] = "En cours d'avis" if votes else "En attente"
    else:
        fav, defa = votes.count("favorable"), votes.count("defavorable")
        d["statut"] = "Validée" if fav > defa else ("Refusée" if defa > fav else "Avis partagés")
    return d["statut"]


def delai_moyen():
    """Délai moyen entre la création d'un dossier et sa décision finale (jours)."""
    finals = [d for d in ss.dossiers if d["statut"] in STATUTS_TERMINAUX and d["decisions"]]
    if not finals:
        return 0.0
    jours = [(max(x["quand"] for x in d["decisions"]) - d["date_creation"]).days for d in finals]
    return sum(jours) / len(jours)


# --- Callbacks simples de navigation -------------------------------------------
def ouvrir_dossier(id_):          # boutons « Ouvrir » : mémorise le dossier à afficher
    ss["voir"] = id_


def fermer_vue():                 # retour au menu : ferme la vue dossier
    ss.pop("voir", None)

# ============================================================================
# 4) 🤖 MOTEUR « IA » (heuristique 100 % local)
# ----------------------------------------------------------------------------
# Chaque fonction ia_*() est autonome : pour brancher un VRAI LLM (OpenAI,
# Mistral, Gemini…), remplacez simplement son corps par un appel API, ex. :
#     def ia_resume(d):
#         return llm.chat("Résume ce dossier d'achat en 3 lignes : " + str(d))
# ============================================================================

def ia_verifier_conformite(d):
    """Contrôle réglementaire du dossier → (score /100, liste des 6 contrôles)."""
    controles = []

    def add(nom, ok, conseil):
        controles.append((nom, ok, conseil))

    add("Cohérence du montant (Quantité × PU)",
        abs(d["quantite"] * d["pu"] - d["montant"]) < 1,
        "Recalculer : le montant ne correspond pas à quantité × prix unitaire.")
    just = (d.get("justification") or "").strip()
    add("Justification technique suffisante", len(just) >= 60,
        "Développer : usage clinique/pédagogique, cadence actuelle, référence produit.")
    add("Fournisseur(s) pressenti(s)", bool((d.get("fournisseur") or "").strip()),
        "Renseigner au moins un fournisseur pressenti (devis concurrents conseillés).")
    add("Procédure adaptée au montant",
        d["montant"] < SEUIL_SIMPLIFIE or bool((d.get("fournisseur") or "").strip()),
        "Au-delà de 50 000 DH : joindre des devis concurrents (consultation restreinte).")
    add("Échéance de validation fixée", d["echeance"] is not None,
        "Fixer une échéance pour rythmer la validation asynchrone.")
    add("Dimensionnement raisonnable", d["quantite"] <= 25,
        "Volumétrie élevée : justifier le nombre d'unités (utilisateurs/salles).")
    score = round(100 * sum(1 for _, ok, _ in controles if ok) / len(controles))
    return score, controles


def ia_resume(d):
    """Résumé exécutif du dossier, style « séance de commission »."""
    if d["montant"] >= SEUIL_APPEL_OFFRES:
        proc = "appel d'offres ouvert"
    elif d["montant"] >= SEUIL_SIMPLIFIE:
        proc = "consultation restreinte"
    else:
        proc = "marché simple"
    ech = d["echeance"].strftime("%d/%m/%Y") if d["echeance"] else "non fixée"
    return (f"{d['ref']} — {d['titre']}. Le service « {d['service']} » demande "
            f"{d['quantite']} unité(s) de {d['categorie'].lower()} pour {dh(d['montant'])} "
            f"(PU {dh(d['pu'])}), procédure : {proc}. Priorité IA : {d['priorite']}. "
            f"Échéance : {ech}. Avis recueillis : {len(d['decisions'])}/{QUORUM}.")


def ia_priorite(d):
    """Priorisation automatique → (étiquette '🥇/🥈/🥉 …', raisons)."""
    texte = " ".join(str(d.get(k, "")) for k in
                     ("titre", "categorie", "description", "justification")).lower()
    critiques = [m for m in ("urgent", "sécurité", "critique", "panne", "immédiat",
                             "norme", "accréditation", "caqued") if m in texte]
    restants = (d["echeance"] - datetime.now().date()).days if d["echeance"] else 999
    if critiques or restants <= 3:
        label = "🥇 Priorité haute"
        raisons = []
        if critiques:
            raisons.append(f"Mots-clés critiques détectés : {', '.join(critiques)}.")
        if restants <= 3:
            raisons.append("Échéance très proche (≤ 3 jours).")
    elif d["montant"] > SEUIL_SIMPLIFIE or restants <= 12:
        label, raisons = "🥈 Priorité moyenne", ["Engagement financier notable ou échéance ≤ 12 jours."]
    else:
        label, raisons = "🥉 Priorité normale", ["Aucun facteur d'urgence détecté."]
    if d["montant"] > SEUIL_APPEL_OFFRES:
        raisons.append("Montant > 100 000 DH : vigilance procédurale renforcée.")
    return label, raisons


def ia_anomalies(d):
    """Détection d'anomalies / points de vigilance."""
    anomal = []
    if d["montant"] > SEUIL_APPEL_OFFRES:
        anomal.append("Montant > 100 000 DH → un appel d'offres OUVERT est normalement obligatoire.")
    if (d.get("fournisseur") or "").strip() and d["montant"] > 8_000:
        anomal.append("Fournisseur unique pressenti et montant > 8 000 DH → exiger 3 devis concurrents.")
    if (d["echeance"] and d["echeance"] < datetime.now().date()
            and d["statut"] not in STATUTS_TERMINAUX):
        anomal.append("Échéance déjà dépassée : dossier à arbitrer en séance.")
    if d["categorie"] == "Mannequins pédagogiques" and d["quantite"] > 6:
        anomal.append(f"Volumétrie atypique pour des mannequins ({d['quantite']}) : vérifier les salles.")
    if len((d.get("description") or "").strip()) < 40:
        anomal.append("Description très courte : risque de mauvaise compréhension par la commission.")
    return anomal or ["✅ Aucune anomalie détectée par les contrôles automatiques."]


MODELES_JUSTIFICATION = {
    "Matériel biomédical": (
        "Le matériel demandé permettra ~[X] actes/semaine au service de [Service]. Le parc actuel "
        "(acquis en [année]) est [état] et ne répond plus au référentiel d'accréditation CAQUED. "
        "Référence produit / fiche technique : [réf]. Compatible avec les consommables et sondes "
        "existants. Incidence budgétaire : {montant} — procédure [à compléter]."),
    "Mannequins pédagogiques": (
        "Formation des internes et doctorants aux gestes de [ACLS/BLS…] (≈ [X] étudiants/an), "
        "conformément au programme de simulation. Parc actuel hors service/partiel. Cadence : "
        "[n] séances/semaine. Fiches techniques : [réf]. Incidence : {montant}."),
    "Matériel informatique": (
        "Renouvellement du parc : [X] postes (OS, licences, câblage). Durée de vie moyenne : 4 ans. "
        "Usage : [cours, secrétariat…]. Référence : [réf]. Incidence : {montant}."),
    "Consommables": (
        "Consommables indispensables aux TP/soins de [service] : gants, compresses, gel HA… "
        "Consommation mensuelle estimée : [X] (registres 2025). Stock restant : [Y]. "
        "Incidence : {montant}."),
}
MODELE_PAR_DEFAUT = ("Justification technique : besoin induit par [activité], cadence [X], "
                     "parc actuel [état], référence produit [réf]. Incidence : {montant}.")


def ia_suggestion_justification(categorie, montant):
    """Modèle de justification pré-rédigé selon la catégorie."""
    modele = MODELES_JUSTIFICATION.get(categorie, MODELE_PAR_DEFAUT)
    return modele.format(montant=dh(montant))


def ia_brouillon_avis(code_sens, score):
    """Brouillon de commentaire motivé, calibré sur le sens choisi."""
    debut = {"favorable": "Avis favorable : dossier conforme en l'état",
             "defavorable": "Avis défavorable : des réserves importantes",
             "neutre": "Je réserve mon avis dans l'attente d'éléments complémentaires",
             "precision": "Demande de précision au service demandeur"}[code_sens]
    fin = (f"Contrôle IA : {score}/100, aucun blocage relevé."
           if code_sens == "favorable"
           else f"Contrôle IA : {score}/100 — voir les points d'attention du dossier.")
    return f"{debut} ({fin})"


def generer_pv(selection):
    """Génère le procès-verbal de la « séance » asynchrone (texte à signer)."""
    lignes = [
        "ROYAUME DU MAROC — Université Ibn Zohr",
        "Faculté de Médecine et de Pharmacie d'Agadir — Service des Marchés",
        f"PV de validation des dossiers d'achat — séance asynchrone du {datetime.now():%d/%m/%Y}",
        "Membres consultés via FMPA VALID : " + ", ".join(m["nom"] for m in COMMISSION),
        "-" * 74,
    ]
    for d in selection:
        lignes.append(f"{d['ref']} — {d['titre']}")
        lignes.append(f"   Service : {d['service']} · Catégorie : {d['categorie']} · Montant : {dh(d['montant'])}")
        lignes.append(f"   Décision : {d['statut']} (quorum {len(d['decisions'])}/{QUORUM})")
        for x in sorted(d["decisions"], key=lambda x: x["quand"]):
            lignes.append(f"   • {x['membre']} : {CODE_VERS_LABEL[x['sens']]} — « {x['commentaire']} »")
        lignes.append("")
    lignes += ["Le présent procès-verbal a été préparé automatiquement par la plateforme",
               "FMPA VALID (validation asynchrone).", "",
               "Le Chef du Service des Marchés            Le Président de la Commission"]
    return "\n".join(lignes)


def ia_chatbot(question):
    """Chatbot « répondeur de commission » : répond à partir des dossiers de la session."""
    q = question.lower()
    en_cours = [d for d in ss.dossiers if d["statut"] not in STATUTS_TERMINAUX]

    # --- 1. Une référence de dossier dans la question ? -----------------------
    m = re.search(r"SM-\d{4}-\d{3}", question, re.IGNORECASE)
    if m:
        d = _dossier_par_ref(m.group(0))
        if d is None:
            return f"❓ Aucun dossier {m.group(0)} dans la session en cours."
        if "anomal" in q:
            return f"⚠️ Anomalies — {d['ref']} :\n\n" + "\n".join(f"• {x}" for x in ia_anomalies(d))
        if "conform" in q:
            sc, _ = ia_verifier_conformite(d)
            return f"✅ Conformité {d['ref']} : **{sc}/100** (détail dans l'onglet « Analyse IA » du dossier)."
        if "résum" in q or "resum" in q:
            return f"🧾 Résumé IA — {d['ref']} :\n\n{ia_resume(d)}"
        ech = d["echeance"].strftime("%d/%m/%Y") if d["echeance"] else "non fixée"
        return (f"📄 {d['ref']} — {d['titre']}\n• Statut : {d['statut']}\n"
                f"• Montant : {dh(d['montant'])} ({d['quantite']} × {dh(d['pu'])})\n"
                f"• Avis : {len(d['decisions'])}/{QUORUM}\n• Échéance : {ech}")

    # --- 2. Questions globales --------------------------------------------------
    if any(k in q for k in ("budget", "montant", "total", "engag")):
        total = sum(d["montant"] for d in en_cours)
        valide = sum(d["montant"] for d in ss.dossiers if d["statut"] in ("Validée", "Clôturée"))
        return (f"💰 Engagement financier :\n• En cours de validation : **{dh(total)}**\n"
                f"• Déjà validés / clôturés : **{dh(valide)}**")
    if any(k in q for k in ("attente", "en cours", "restant", "liste")):
        if not en_cours:
            return "🎉 Aucun dossier en attente : la commission est à jour !"
        l = "\n".join(f"• **{d['ref']}** — {d['titre']} ({d['statut']}, {len(d['decisions'])}/{QUORUM} avis)"
                      for d in en_cours)
        return f"📋 {len(en_cours)} dossier(s) en attente d'avis :\n\n{l}"
    if any(k in q for k in ("priorit", "urgent", "premi")):
        tri = sorted(en_cours, key=lambda d: (RANG_PRIORITE.get(d["priorite"][0], 3),
                                              d["echeance"] or date.max))[:3]
        l = "\n".join(f"• {d['priorite']} — **{d['ref']}** : {d['titre']}" for d in tri)
        return (f"🥇 Priorités selon l'IA :\n\n{l}" if tri
                else "🎉 Rien de prioritaire en ce moment.")
    if any(k in q for k in ("valid", "refus", "décis", "decis", "bilan")):
        valide = [d for d in ss.dossiers if d["statut"] in ("Validée", "Clôturée")]
        refuse = [d for d in ss.dossiers if d["statut"] == "Refusée"]
        return (f"📊 Bilan : **{len(valide)} validé(s)**, {len(refuse)} refusé(s), "
                f"{len(en_cours)} en cours. Délai moyen : {delai_moyen():.1f} jours "
                f"(vs **4 semaines** en réunion physique).")
    if any(k in q for k in ("échéance", "echeance", "retard", "date")):
        proches = sorted([d for d in en_cours if d["echeance"]], key=lambda d: d["echeance"])[:3]
        if not proches:
            return "📅 Aucune échéance proche."
        l = "\n".join(f"• **{d['ref']}** — échéance {d['echeance'].strftime('%d/%m/%Y')}" for d in proches)
        return f"⏳ Échéances les plus proches :\n\n{l}"
    return ("🤖 Posez-moi par exemple :\n"
            "• « Quels dossiers sont en attente ? »\n"
            "• « Résume-moi SM-2026-002 »\n"
            "• « Conformité de SM-2026-006 »\n"
            "• « Quel est le budget total engagé ? »\n"
            "• « Quels dossiers sont prioritaires ? »")

# ============================================================================
# 6) DONNÉES DE DÉMONSTRATION (graine réaliste, créée une seule fois)
# ============================================================================
def initialiser_donnees():
    """Crée, au premier lancement, 9 dossiers crédibles pour l'application."""
    if "dossiers" in ss:
        return
    t0 = datetime.now()

    def avis_fix(mid, sens, commentaire, heures):
        """Un avis déjà déposé il y a `heures` heures."""
        m = next(u for u in COMMISSION if u["id"] == mid)
        return {"membre_id": mid, "membre": m["nom"], "sens": sens,
                "commentaire": commentaire, "quand": t0 - timedelta(hours=heures)}

    D = [
        dict(id=1, ref="SM-2026-001", titre="Mannequins de simulation ACLS (6 unités)",
             service="Département de Médecine", categorie="Mannequins pédagogiques",
             quantite=6, pu=9500, fournisseur="MedSim Maroc (devis 2026-041)",
             description="Renouvellement des mannequins de la salle de simulation : formation "
                         "ACLS/BLS des internes (≈ 120 étudiants/an). Mannequins actuels hors service "
                         "depuis février.",
             justification="Formation obligatoire des internes (120 étudiants/an). Parc HS depuis "
                           "février ; cadence 3 séances/semaine. Fiche technique jointe.",
             date_creation=t0 - timedelta(days=6),
             echeance=(t0 - timedelta(days=1)).date(),
             decisions=[avis_fix("P1", "favorable", "Dossier bien cadré, conforme aux besoins de la simulation.", 96),
                        avis_fix("P2", "favorable", "Indispensable au programme ; je valide.", 72),
                        avis_fix("P3", "favorable", "OK pour ma part, usage clinique documenté.", 48),
                        avis_fix("P4", "favorable", "Montant cohérent avec les prix du marché.", 24)]),
        dict(id=2, ref="SM-2026-002", titre="Échographe portable — Service des Urgences",
             service="Polyclinique universitaire", categorie="Matériel biomédical",
             quantite=1, pu=86000, fournisseur="UltraMed (devis 2026-027)",
             description="Échographe portable pour les urgences vitales : protocoles eFAST au lit du "
                         "malade (sécurité patient).",
             justification="≈ 25 actes/semaine aux urgences ; gain de diagnostic < 10 min ; compatible "
                           "avec les sondes existantes. Fiche technique jointe.",
             date_creation=t0 - timedelta(days=4),
             echeance=(t0 + timedelta(days=2)).date(),
             decisions=[avis_fix("P1", "favorable", "Équipement de sécurité : avis favorable (mon domaine).", 60),
                        avis_fix("P3", "defavorable", "Un seul devis à 86 000 DH : exiger deux devis concurrents avant validation.", 40)]),
        dict(id=3, ref="SM-2026-003", titre="Lot de consommables (gants, compresses, gel HA)",
             service="Département de Pharmacie", categorie="Consommables",
             quantite=500, pu=25, fournisseur="",
             description="Consommables pour les TP de galénique et l'hygiène des locaux de TP.",
             justification="Reconstitution mensuelle du stock ; consommation moyenne 450 unités/mois "
                           "d'après les registres 2025.",
             date_creation=t0 - timedelta(days=2),
             echeance=(t0 + timedelta(days=10)).date(), decisions=[]),
        dict(id=4, ref="SM-2026-004", titre="12 ordinateurs portables — salle pédagogique",
             service="Service Informatique", categorie="Matériel informatique",
             quantite=12, pu=7800, fournisseur="Alpha Informatique",
             description="Renouvellement des postes de la salle pédagogique (4 à 6 ans d'âge) et du "
                         "secrétariat pédagogique.",
             justification="Parc en fin de vie, pannes récurrentes ; usage : TP d'informatique médicale "
                           "et examens.",
             date_creation=t0 - timedelta(days=7),
             echeance=(t0 + timedelta(days=7)).date(), decisions=[]),
        dict(id=5, ref="SM-2026-005", titre="40 ouvrages de pharmacologie récents",
             service="Bibliothèque universitaire", categorie="Ouvrages & documentation",
             quantite=40, pu=350, fournisseur="Librairie Ibn Sina",
             description="Éditions récentes de pharmacologie et thérapeutique pour la bibliothèque.",
             justification="Mise à jour du fonds documentaire recommandée par le conseil pédagogique "
                           "(éditions 2024-2026).",
             date_creation=t0 - timedelta(days=3),
             echeance=(t0 + timedelta(days=5)).date(),
             decisions=[avis_fix("P2", "precision", "Merci de joindre la liste des 40 titres proposés avec les ISBN.", 20)]),
        dict(id=6, ref="SM-2026-006", titre="Table de dissection anatomique (2 unités)",
             service="Laboratoire d'Anatomie", categorie="Matériel biomédical",
             quantite=2, pu=68500, fournisseur="AtlasLab",
             description="Tables de dissection avec aspiration et éclairage LED, en remplacement de la "
                         "table défectueuse du laboratoire.",
             justification="Travaux pratiques d'anatomie (≈ 200 étudiants/an) ; table actuelle hors "
                           "service depuis 3 mois.",
             date_creation=t0 - timedelta(days=8),
             echeance=(t0 + timedelta(days=12)).date(), decisions=[]),
        dict(id=7, ref="SM-2026-007", titre="20 fauteuils ergonomiques — bureaux des enseignants",
             service="Administration générale", categorie="Mobilier de bureau",
             quantite=20, pu=2200, fournisseur="ConfortPro",
             description="Fauteuils ergonomiques pour les bureaux des enseignants-chercheurs.",
             justification="Confort et prévention des troubles musculo-squelettiques ; mobilier en fin de vie.",
             date_creation=t0 - timedelta(days=10),
             echeance=(t0 - timedelta(days=2)).date(),
             decisions=[avis_fix("P1", "defavorable", "Redondant avec le lot de mobilier acquis en 2024 : justifier l'urgence.", 100),
                        avis_fix("P2", "favorable", "Confort des enseignants important, mais demande à affiner.", 80),
                        avis_fix("P3", "defavorable", "Priorité au matériel biomédical cette année ; report souhaitable.", 60),
                        avis_fix("P4", "defavorable", "Budget mieux employé ailleurs : avis défavorable.", 40)]),
        dict(id=8, ref="SM-2026-008", titre="Imprimante multifonction A3 — Service des Marchés",
             service="Administration générale", categorie="Matériel informatique",
             quantite=1, pu=9000, fournisseur="Alpha Informatique",
             description="Imprimante recto/verso A3 pour l'édition des relevés et des PV du service.",
             justification="Impressions quotidiennes (≈ 150 pages/jour) ; l'ancienne imprimante est en panne.",
             date_creation=t0 - timedelta(days=14),
             echeance=(t0 - timedelta(days=5)).date(),
             decisions=[avis_fix("P1", "favorable", "Équipement indispensable au service ; favorable.", 120),
                        avis_fix("P2", "favorable", "Favorable.", 96),
                        avis_fix("P3", "favorable", "Favorable.", 72),
                        avis_fix("P4", "favorable", "Favorable, prix maîtrisé.", 48)]),
        dict(id=9, ref="SM-2026-009", titre="Kit de simulation dentaire — 4 phantom heads",
             service="Département de Médecine Dentaire", categorie="Mannequins pédagogiques",
             quantite=4, pu=21000, fournisseur="DentSim",
             description="Simulateurs odontologiques (phantom heads) exigés par le référentiel "
                         "d'accréditation CAQUED.",
             justification="Exigence de l'accréditation CAQUED pour les TP de prothèse ; équipement "
                           "critique pour la visite de l'agence.",
             date_creation=t0 - timedelta(days=1),
             echeance=(t0 + timedelta(days=2)).date(), decisions=[]),
    ]
    for d in D:                       # montants, priorité IA et statut auto
        d["montant"] = d["quantite"] * d["pu"]
        d["relances"] = 0
        d["priorite"] = ia_priorite(d)[0]
        mettre_a_jour_statut(d)
    D[7]["statut"] = "Clôturée"       # dossier déjà transmis à la Direction (démo)
    ss.dossiers = D
    ss.prochain_id = len(D) + 1

# ============================================================================
# 7) LOGIQUE MÉTIER : enregistrer un avis, brouillons IA, clôture, relance
# ============================================================================
def enregistrer_avis(id_dossier, uid):
    """Callback : enregistre (ou remplace) l'avis du membre connecté."""
    d = next(x for x in ss.dossiers if x["id"] == id_dossier)
    if d["statut"] in STATUTS_TERMINAUX:               # quorum déjà atteint
        st.toast("🔒 Quorum atteint : la décision est figée, modification impossible.", icon="🔒")
        return
    code = SENS[ss[f"sens_{d['ref']}"]]
    commentaire = ss[f"avis_{d['ref']}"].strip()
    # Cohérence métier : les décisions « fortes » exigent un avis motivé
    if code in ("defavorable", "precision") and len(commentaire) < 10:
        st.toast("⚠️ Avis motivé requis (≥ 10 caractères) pour une décision défavorable "
                 "ou une demande de précision.", icon="⚠️")
        return
    d["decisions"] = [x for x in d["decisions"] if x["membre_id"] != uid]
    d["decisions"].append({"membre_id": uid,
                           "membre": next(u["nom"] for u in UTILISATEURS if u["id"] == uid),
                           "sens": code, "commentaire": commentaire, "quand": datetime.now()})
    statut = mettre_a_jour_statut(d)
    st.toast(f"🗳️ Avis enregistré — {d['ref']} → {statut}", icon="✅")


def faire_brouillon(id_dossier):
    """Callback : insère un brouillon d'avis IA dans la zone de commentaire."""
    d = next(x for x in ss.dossiers if x["id"] == id_dossier)
    code = SENS[ss.get(f"sens_{d['ref']}", "✅ Favorable")]
    sc, _ = ia_verifier_conformite(d)
    ss[f"avis_{d['ref']}"] = ia_brouillon_avis(code, sc)
    st.toast("🪄 Brouillon IA inséré — relisez-le et personnalisez-le.", icon="🤖")


def relancer(id_dossier):
    """Callback (admin) : notifie les membres qui n'ont pas encore voté."""
    d = next(x for x in ss.dossiers if x["id"] == id_dossier)
    d["relances"] = d.get("relances", 0) + 1
    st.toast("🔔 Relance envoyée aux membres qui n'ont pas voté (simulation e-mail / SMS).", icon="🔔")


def clore(id_dossier):
    """Callback (admin) : clôture un dossier ayant une décision finale."""
    d = next(x for x in ss.dossiers if x["id"] == id_dossier)
    d["statut"] = "Clôturée"
    st.toast("📌 Dossier clôturé — le PV est disponible dans « Rapports & PV ».", icon="📌")

# ============================================================================
# 8) PAGES : CONNEXION, SIDEBAR, TABLEAU DE BORD, LISTE DOSSIERS, DÉTAIL
# ============================================================================
def page_connexion():
    """Écran d'accueil + choix du profil de démonstration."""
    st.markdown("""<div class="fmp-hero"><h1>🏥 FMPA VALID — Validation asynchrone des achats</h1>
    <p>Service des Marchés · Faculté de Médecine et de Pharmacie d'Agadir (Université Ibn Zohr)</p></div>""",
                unsafe_allow_html=True)
    gauche, droite = st.columns([2, 3])
    with gauche:
        st.markdown("#### 👤 Identification (démo)")
        labels = [f"{u['nom']} — {u['role']}" for u in UTILISATEURS]
        choix = st.selectbox("Choisissez votre profil", labels)
        if st.button("Se connecter", type="primary", use_container_width=True):
            ss.connecte_id = UTILISATEURS[labels.index(choix)]["id"]
            st.rerun()
        st.caption("🔒 Projet pédagogique : aucune donnée réelle. En production : "
                   "SSO/LDAP de l'université + base de données.")
    with droite:
        st.markdown("""##### Le principe en 4 étapes
        1️⃣ Le Service des Marchés **crée le dossier** → l'IA le résume, le contrôle et le priorise.
        2️⃣ Les 4 membres donnent leur avis **en différé**, où qu'ils soient (cours, garde, consultation).
        3️⃣ Au quorum atteint, la décision se calcule automatiquement (majorité simple).
        4️⃣ L'IA **génère le PV** ; la réunion physique ne reste nécessaire que pour les « avis partagés ».
        ⏱️ Objectif : passer de **4 semaines → 3 jours** de validation.""")


def barre_laterale(user):
    """Sidebar : profil, navigation (radio persistée en session), zone démo."""
    with st.sidebar:
        ico = "🧑‍💼" if user["role"] == "Administrateur" else "🎓"
        st.markdown(f"### {ico} {user['nom']}")
        st.caption(f"{user['role']} · {user['specialite']}")
        st.divider()
        options = MENUS[user["role"]]
        # Sécurité : si l'utilisateur change de rôle, le menu choisi peut ne plus exister
        if "menu_nav" in ss and ss.menu_nav not in options:
            del ss["menu_nav"]
            st.rerun()
        menu = st.radio("Navigation", options, key="menu_nav",
                        on_change=fermer_vue, label_visibility="collapsed")
        st.divider()
        if st.button("🚪 Se déconnecter", use_container_width=True):
            for cle in ("connecte_id", "voir", "chat"):
                ss.pop(cle, None)
            st.rerun()
        with st.expander("⚙️ Zone de démonstration"):
            ok = st.checkbox("Je confirme la réinitialisation")
            if st.button("🧹 Réinitialiser la démo", disabled=not ok, use_container_width=True):
                for cle in ("dossiers", "prochain_id", "voir", "chat", "connecte_id"):
                    ss.pop(cle, None)
                st.rerun()
        st.caption("💾 Données de démonstration vivantes, stockées en session.")
    return menu


def page_tableau_bord(user):
    """Accueil : indicateurs, graphiques, priorités IA et échéances."""
    st.title("🏠 Tableau de bord — Service des Marchés")
    D = ss.dossiers
    en_cours = [d for d in D if d["statut"] not in STATUTS_TERMINAUX]
    finals = [d for d in D if d["statut"] in STATUTS_TERMINAUX]
    conformite = [ia_verifier_conformite(d)[0] for d in D]

    # ─── Indicateurs clés ───────────────────────────────────────────────────────
    c = st.columns(5)
    c[0].metric("📚 Dossiers suivis", len(D))
    c[1].metric("⏳ En validation", len(en_cours))
    c[2].metric("🗳️ Décisions rendues", len(finals))
    c[3].metric("⏱️ Délai moyen", f"{delai_moyen():.1f} j", "vs 4 semaines en réunion")
    c[4].metric("✅ Conformité IA", f"{sum(conformite) / len(conformite):.0f}/100")

    # ─── Graphiques ─────────────────────────────────────────────────────────────
    gauche, droite = st.columns(2)
    with gauche:
        st.subheader("Situation des dossiers")
        serie = pd.Series({s: sum(1 for d in D if d["statut"] == s) for s in STATUTS})
        st.bar_chart(serie[serie > 0])
    with droite:
        st.subheader("Engagement financier par catégorie")
        agg = pd.DataFrame([{"Catégorie": d["categorie"], "Montant": d["montant"]}
                            for d in D]).groupby("Catégorie")["Montant"].sum()
        st.bar_chart(agg)

    # ─── Action : priorités IA + échéances ──────────────────────────────────────
    bloc1, bloc2 = st.columns([1.4, 1])
    with bloc1:
        st.subheader("🧭 À traiter en priorité (classement IA)")
        tri = sorted(en_cours, key=lambda d: (RANG_PRIORITE.get(d["priorite"][0], 3),
                                              d["echeance"] or date.max))[:4]
        for d in tri:
            with st.container(border=True):
                infos, btn = st.columns([6, 2])
                infos.markdown(badge_priorite(d["priorite"]) + badge_statut(d["statut"])
                               + f" **{d['ref']} · {d['titre']}**", unsafe_allow_html=True)
                infos.caption(extrait(d["description"]))
                btn.button("🔎 Ouvrir", key=f"act{d['id']}", use_container_width=True,
                           on_click=ouvrir_dossier, args=(d["id"],))
        if not tri:
            st.success("Rien d'urgent : la commission est à jour ✅")
    with bloc2:
        st.subheader("⏳ Échéances proches")
        proches = sorted([d for d in en_cours if d["echeance"]], key=lambda d: d["echeance"])[:5]
        for d in proches:
            reste = (d["echeance"] - datetime.now().date()).days
            etat = f"dans {reste} j" if reste >= 0 else f"**dépassée** ({-reste} j)"
            st.markdown(f"- **{d['ref']}** — {extrait(d['titre'], 46)} · {etat}")
        if not proches:
            st.success("Aucune échéance imminente.")

    votes = sum(len(d["decisions"]) for d in D)
    st.caption(f"⚡ **Gain estimé par l'IA** : {votes * MN_REUNION_PAR_DECISION // 60} h de réunion "
               f"évitées ({votes} avis donnés en différé × {MN_REUNION_PAR_DECISION} min).")


def page_dossiers(user):
    """Liste filtrable de tous les dossiers + accès au détail."""
    st.title("📋 Dossiers d'achat")
    D = ss.dossiers
    f1, f2, f3 = st.columns([1.2, 1.5, 2.2])
    statut = f1.selectbox("Statut", ["Tous"] + list(STATUTS))
    service = f2.selectbox("Service demandeur", ["Tous"] + SERVICES)
    cherche = f3.text_input("🔎 Recherche (référence, titre, description)")

    vus = [d for d in D
           if (statut == "Tous" or d["statut"] == statut)
           and (service == "Tous" or d["service"] == service)
           and (not cherche or cherche.lower() in f"{d['ref']} {d['titre']} {d['description']}".lower())]
    vus.sort(key=lambda d: (RANG_PRIORITE.get(d["priorite"][0], 3), d["echeance"] or date.max))
    st.caption(f"{len(vus)} dossier(s) affiché(s) · tri par priorité IA et échéance")
    if not vus:
        st.info("Aucun dossier ne correspond aux filtres saisis.")

    for d in vus:
        with st.container(border=True):
            infos, mont, act = st.columns([5.8, 2.2, 2])
            with infos:
                st.markdown(f"**{d['ref']} · {d['titre']}**")
                st.markdown(badge_statut(d["statut"]) + badge_priorite(d["priorite"])
                            + chip("🏫 " + extrait(d["service"], 30), "#eef3fa")
                            + chip("🗂️ " + d["categorie"], "#f4eefa"), unsafe_allow_html=True)
                st.caption(extrait(d["description"]))
            with mont:
                st.metric("Montant", dh(d["montant"]))
                st.caption(f"{d['quantite']} × {dh(d['pu'])}/unité")
            with act:
                reste = (d["echeance"] - datetime.now().date()).days if d["echeance"] else None
                if reste is None:
                    ligne = "🎯 Échéance : non fixée"
                else:
                    ligne = (f"🎯 {d['echeance'].strftime('%d/%m')} · dans {reste} j"
                             if reste >= 0 else f"🎯 {d['echeance'].strftime('%d/%m')} · ⚠️ {-reste} j de retard")
                st.markdown(f"🗳️ **{len(d['decisions'])}/{QUORUM}** avis\n\n{ligne}")
                st.button("🔎 Ouvrir le dossier", key=f"ouvrir{d['id']}", use_container_width=True,
                          on_click=ouvrir_dossier, args=(d["id"],))


def page_detail(id_dossier, user):
    """Vue complète d'un dossier : infos, analyse IA, votes, actions admin."""
    d = next((x for x in ss.dossiers if x["id"] == id_dossier), None)
    if d is None:
        st.warning("Dossier introuvable.")
        st.button("← Retour", on_click=fermer_vue)
        return

    st.button("← Revenir à la liste", on_click=fermer_vue)
    titre, montant_bloc = st.columns([7, 3])
    with titre:
        st.markdown(badge_statut(d["statut"]) + badge_priorite(d["priorite"])
                    + chip("🗂️ " + d["categorie"], "#f4eefa")
                    + chip("🏫 " + d["service"], "#eef3fa"), unsafe_allow_html=True)
        st.title(f"{d['ref']} — {d['titre']}")
    with montant_bloc:
        st.metric("Montant total", dh(d["montant"]))
        reste = (d["echeance"] - datetime.now().date()).days if d["echeance"] else None
        if reste is not None:
            detail = (f"🎯 Éch. {d['echeance'].strftime('%d/%m/%Y')} : dans {reste} j"
                      if reste >= 0 else f"🎯 Éch. {d['echeance'].strftime('%d/%m/%Y')} : ⚠️ dépassée de {-reste} j")
            st.caption(detail)

    gauche, droite = st.columns([1.8, 1.2], gap="large")

    # ─── Colonne gauche : caractéristiques + analyse IA ────────────────────────
    with gauche:
        st.subheader("🧾 Caractéristiques")
        k1, k2, k3 = st.columns(3)
        k1.metric("Quantité", d["quantite"])
        k2.metric("Prix unitaire", dh(d["pu"]))
        k3.metric("Créé le", d["date_creation"].strftime("%d/%m/%Y"))
        st.markdown(f"**Fournisseur(s) pressenti(s) :** {d['fournisseur'] or '— (aucun renseigné)'}")
        with st.expander("📝 Description du besoin"):
            st.write(d["description"])
        with st.expander("🧠 Analyse IA complète (moteur local, prêt pour un LLM)", expanded=True):
            onglets = st.tabs(["🧾 Résumé & priorité", "✅ Conformité", "⚠️ Anomalies & arguments"])
            with onglets[0]:
                st.info(ia_resume(d))
                st.markdown(f"**Priorité IA :** {d['priorite']}")
                for raison in ia_priorite(d)[1]:
                    st.caption("• " + raison)
            with onglets[1]:
                sc, controles = ia_verifier_conformite(d)
                st.markdown(f"#### Score global : {sc}/100")
                st.progress(sc)
                for nom, ok, conseil in controles:
                    if ok:
                        st.success("✅ " + nom)
                    else:
                        st.warning("⚠️ " + nom + " — " + conseil)
            with onglets[2]:
                alertes = ia_anomalies(d)
                for a in alertes:
                    (st.success(a) if a.startswith("✅") else st.warning("⚠️ " + a))
                st.divider()
                bloquantes = [a for a in alertes if not a.startswith("✅")]
                st.markdown("**🧲 Arguments pour le débat (préparés par l'IA)**")
                st.markdown("- **Pour :** besoin documenté, échéance posée, contrôle IA complet ; "
                            "validation en différé sans déplacer les professeurs.")
                if bloquantes:
                    st.markdown("- **Contre / à vérifier :** " + " ".join(bloquantes))
                else:
                    st.markdown("- **Contre :** rien de bloquant relevé automatiquement.")

    # ─── Colonne droite : décisions de la commission ───────────────────────────
    with droite:
        st.subheader("🗳️ Décision de la commission")
        st.progress(len(d["decisions"]) / QUORUM,
                    text=f"{len(d['decisions'])}/{QUORUM} avis recueillis")
        votes = {x["membre_id"]: x for x in d["decisions"]}
        lignes = [{"Membre": m["nom"],
                   "Décision": CODE_VERS_LABEL[votes[m["id"]]["sens"]] if m["id"] in votes else "⏳ En attente",
                   "Le": votes[m["id"]]["quand"].strftime("%d/%m %H:%M") if m["id"] in votes else "—"}
                  for m in COMMISSION]
        st.dataframe(pd.DataFrame(lignes), hide_index=True, use_container_width=True)

        if d["statut"] == "Clôturée":
            st.success("📌 Dossier clôturé et transmis à la Direction.")
        elif d["statut"] in ("Validée", "Refusée", "Avis partagés"):
            st.info(f"🎯 Quorum atteint — décision finale : {d['statut']}")
            if user["role"] == "Administrateur":
                st.button("📌 Clôturer & transmettre", type="primary", use_container_width=True,
                          on_click=clore, args=(d["id"],))
        elif user["role"] == "Membre":
            k_sens, k_avis = f"sens_{d['ref']}", f"avis_{d['ref']}"
            mon_avis = next((x for x in d["decisions"] if x["membre_id"] == user["id"]), None)
            if k_avis not in ss:                      # pré-remplissage une seule fois
                ss[k_avis] = mon_avis["commentaire"] if mon_avis else ""
            st.radio("Ma décision", list(SENS), key=k_sens, horizontal=True,
                     index=list(SENS.values()).index(mon_avis["sens"]) if mon_avis else 0)
            st.text_area("Avis motivé", key=k_avis, height=130,
                         help="Obligatoire (≥ 10 caractères) pour « Défavorable » et « Demande de précision ».")
            c1, c2 = st.columns(2)
            c1.button("🪄 Brouillon IA", key=f"dft{d['id']}", use_container_width=True,
                      on_click=faire_brouillon, args=(d["id"],))
            c2.button("📨 Enregistrer mon avis", key=f"val{d['id']}", type="primary",
                      use_container_width=True, on_click=enregistrer_avis, args=(d["id"], user["id"]))
            if mon_avis:
                st.caption(f"Avis actuel : {CODE_VERS_LABEL[mon_avis['sens']]} — modifiable tant que "
                           "le quorum n'est pas atteint.")
        elif user["role"] == "Administrateur":
            st.caption(f"⏳ Validation en cours : {len(d['decisions'])}/{QUORUM} avis recueillis.")
            st.button("🔔 Relancer les membres", use_container_width=True,
                      on_click=relancer, args=(d["id"],))

# ============================================================================
# 9) PAGES : NOUVEAU DOSSIER, MES VALIDATIONS, ASSISTANT IA, RAPPORTS & PV
# ============================================================================
def garder_pv(selection):
    """Callback (admin) : mémorise le PV généré dans la zone de texte modifiable."""
    ss["zone_pv"] = generer_pv(selection)
    st.toast("🪄 PV généré automatiquement — relisez-le, modifiez-le, puis téléchargez-le.", icon="🪄")


def page_nouveau(user):
    """Création d'un dossier (Service des Marchés) avec aperçu IA en direct."""
    st.title("➕ Nouveau dossier d'achat")
    st.caption("Le Service des Marchés crée le dossier ; l'IA le contrôle, le résume et le met en forme "
               "pour la commission.")
    bloc_saisie, apercu = st.columns([2.1, 1])
    with bloc_saisie:
        st.text_input("Titre du dossier", key="nd_titre",
                      placeholder="Ex. : Mannequins de simulation BLS (4 unités)")
        s1, s2 = st.columns(2)
        s1.selectbox("Service demandeur", SERVICES, key="nd_service")
        s2.selectbox("Catégorie", CATEGORIES, key="nd_cat")
        s3, s4 = st.columns(2)
        s3.number_input("Quantité", min_value=1, max_value=500, value=1, key="nd_quantite")
        s4.number_input("Prix unitaire (DH)", min_value=0, max_value=5_000_000,
                        value=0, step=500, key="nd_pu")
        st.text_input("Fournisseur(s) pressenti(s) — optionnel", key="nd_four",
                      placeholder="2 à 3 devis concurrents recommandés au-delà de 50 000 DH")
        st.text_area("Description du besoin", key="nd_desc", height=110,
                     placeholder="Contexte, usage quotidien, effectifs concernés, matériel actuel…")
        if st.button("🪄 Me suggérer une justification technique (IA)", key="nd_btn_justif"):
            ss["nd_justif"] = ia_suggestion_justification(ss["nd_cat"],
                                                          ss["nd_quantite"] * ss["nd_pu"])
            st.rerun()
        st.text_area("Justification technique (modèle IA, modifiable)", key="nd_justif", height=140)
        st.date_input("Échéance de validation souhaitée",
                      value=datetime.now().date() + timedelta(days=15),
                      min_value=datetime.now().date(), format="DD/MM/YYYY", key="nd_ech")

        if st.button("✅ Soumettre à la commission", type="primary"):
            montant = int(ss["nd_quantite"]) * int(ss["nd_pu"])
            if not ss["nd_titre"].strip():
                st.error("Le titre est obligatoire.")
            elif montant <= 0:
                st.error("Montant invalide (quantité × prix unitaire = 0).")
            elif len(ss["nd_desc"].strip()) < 15:
                st.error("Décrivez le besoin (≥ 15 caractères) pour permettre l'analyse IA.")
            else:
                d = dict(id=ss.prochain_id, ref=f"SM-2026-{ss.prochain_id:03d}",
                         titre=ss["nd_titre"].strip(), service=ss["nd_service"],
                         categorie=ss["nd_cat"], quantite=int(ss["nd_quantite"]),
                         pu=int(ss["nd_pu"]), montant=montant, fournisseur=ss["nd_four"].strip(),
                         description=ss["nd_desc"].strip(), justification=ss["nd_justif"].strip(),
                         date_creation=datetime.now(), echeance=ss["nd_ech"],
                         decisions=[], relances=0, statut="En attente")
                d["priorite"] = ia_priorite(d)[0]
                ss.dossiers.append(d)
                ss.prochain_id += 1
                sc, _ = ia_verifier_conformite(d)
                st.toast(f"🚀 Dossier {d['ref']} diffusé aux 4 membres (conformité IA : {sc}/100, "
                         f"priorité : {d['priorite']}).", icon="🚀")
                ss["voir"] = d["id"]
                st.rerun()
    with apercu:
        st.markdown("#### 👁️ Aperçu IA en direct")
        montant = int(ss.get("nd_quantite", 1)) * int(ss.get("nd_pu", 0))
        st.metric("Montant total", dh(montant))
        if montant >= SEUIL_APPEL_OFFRES:
            st.warning("⚖️ Procédure : **appel d'offres ouvert** (> 100 000 DH)")
        elif montant >= SEUIL_SIMPLIFIE:
            st.info("📋 Procédure : **consultation restreinte** (> 50 000 DH)")
        else:
            st.success("🧾 Procédure : **marché simple** (< 50 000 DH)")
        st.markdown(chip("🟠 En attente", STATUTS["En attente"][1])
                    + chip("🗂️ " + ss.get("nd_cat", "—"), "#f4eefa")
                    + chip("🏫 " + extrait(ss.get("nd_service", "—"), 28), "#eef3fa"),
                    unsafe_allow_html=True)
        st.caption("À la diffusion : résumé IA + score de conformité + priorité calculés automatiquement.")


def page_mes_validations(user):
    """Page dédiée aux membres : la liste de ce qui attend PERSONNELLEMENT leur avis."""
    st.title("✍️ Mes validations en attente")
    D = ss.dossiers
    a_traiter = [d for d in D
                 if d["statut"] not in STATUTS_TERMINAUX
                 and not any(x["membre_id"] == user["id"] for x in d["decisions"])]
    deja = [d for d in D if any(x["membre_id"] == user["id"] for x in d["decisions"])]
    k1, k2, k3 = st.columns(3)
    k1.metric("⏳ À traiter", len(a_traiter))
    k2.metric("🗳️ Déjà traités", len(deja))
    eche = min((d["echeance"] for d in a_traiter if d["echeance"]), default=None)
    k3.metric("🎯 Prochaine échéance", eche.strftime("%d/%m/%Y") if eche else "—")

    if not a_traiter:
        st.success("🎉 Vous êtes à jour ! Aucun dossier n'attend votre avis.")
        return
    st.caption("Lisez l'analyse IA puis rendez votre avis — 2 minutes suffisent, où que vous soyez.")
    for d in sorted(a_traiter, key=lambda x: (RANG_PRIORITE.get(x["priorite"][0], 3),
                                              x["echeance"] or date.max)):
        with st.container(border=True):
            infos, act = st.columns([7, 2])
            infos.markdown(badge_priorite(d["priorite"]) + badge_statut(d["statut"])
                           + f" **{d['ref']} · {d['titre']}**", unsafe_allow_html=True)
            infos.caption(extrait(d["description"], 90))
            act.metric("Montant", dh(d["montant"]))
            act.button("🔎 Rendre mon avis", key=f"mv{d['id']}", use_container_width=True,
                       on_click=ouvrir_dossier, args=(d["id"],))


def poser_au_chat(question):
    """Callback des « puces » de questions rapides : ajoute Q + R IA au fil."""
    def cb():
        ss.setdefault("chat", []).append({"role": "user", "content": question})
        time.sleep(0.5)                      # petit temps de réflexion simulé
        ss["chat"].append({"role": "assistant", "content": ia_chatbot(question)})
    return cb


def page_assistant(user):
    """Chatbot : questions/réponses en langage naturel sur les dossiers."""
    st.title("🤖 Assistant IA — répondeur de commission")
    st.caption("Interrogez les dossiers en langage naturel. Moteur heuristique local ; "
               "branchable sur un vrai LLM (Mistral, OpenAI…) en remplaçant `ia_chatbot()`.")
    puces = ["Quels dossiers sont en attente ?", "Résume-moi SM-2026-002",
             "Conformité de SM-2026-006", "Quel est le budget total engagé ?",
             "Quels dossiers sont prioritaires ?"]
    colonnes = st.columns(len(puces))
    for i, q in enumerate(puces):
        colonnes[i].button(q, key=f"puce{i}", use_container_width=True, on_click=poser_au_chat(q))
    st.divider()
    for msg in ss.get("chat", []):
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])
    question = st.chat_input("Votre question… (ex. : résume-moi SM-2026-003)")
    if question:
        ss.setdefault("chat", []).append({"role": "user", "content": question})
        with st.chat_message("assistant"), st.spinner("Analyse des dossiers…"):
            time.sleep(0.6)
            reponse = ia_chatbot(question)
            st.markdown(reponse)
        ss["chat"].append({"role": "assistant", "content": reponse})
        st.rerun()


def page_rapports(user):
    """Réservé à l'admin : PV de séance généré par l'IA + export CSV."""
    st.title("📄 Rapports & PV de séance")
    st.caption("Le PV asynchrone regroupe les décisions rendues — prêt à signer et à archiver.")
    finals = [d for d in ss.dossiers if d["statut"] in STATUTS_TERMINAUX]
    choix = st.multiselect("Dossiers à inclure dans le PV", finals,
                           default=[d for d in finals if d["statut"] in ("Validée", "Refusée", "Avis partagés")],
                           format_func=lambda d: f"{d['ref']} — {d['titre']}")
    st.button("🪄 Générer le PV de séance", type="primary", disabled=not choix,
              use_container_width=True, on_click=garder_pv, args=(choix,))
    st.text_area("Procès-verbal (modifiable avant export)", key="zone_pv", height=320)
    if "zone_pv" in ss and ss["zone_pv"].strip():
        flux = io.BytesIO(ss["zone_pv"].encode("utf-8"))
        st.download_button("⬇️ Télécharger le PV (.txt)", flux,
                           file_name=f"PV_FMPA_{datetime.now():%Y%m%d}.txt",
                           mime="text/plain", use_container_width=True)

    st.divider()
    st.subheader("📦 Export suivi / comptabilité")
    df = pd.DataFrame([{"Référence": d["ref"], "Intitulé": d["titre"], "Service": d["service"],
                        "Catégorie": d["categorie"], "Quantité": d["quantite"], "PU (DH)": d["pu"],
                        "Montant (DH)": d["montant"], "Statut": d["statut"],
                        "Avis": f"{len(d['decisions'])}/{QUORUM}", "Priorité IA": d["priorite"],
                        "Échéance": d["echeance"].strftime("%d/%m/%Y") if d["echeance"] else ""}
                       for d in ss.dossiers])
    tampon = io.BytesIO()
    df.to_csv(tampon, index=False, sep=";", encoding="utf-8-sig")
    st.download_button("⬇️ Exporter tous les dossiers (.csv)", tampon.getvalue(),
                       file_name="dossiers_fmpa.csv", mime="text/csv", use_container_width=True)
    st.dataframe(df, hide_index=True, use_container_width=True)

# ============================================================================
# 10) 🧭 EXTENSIONS EN VUE RÉELLE (pistes de déploiement)
# ----------------------------------------------------------------------------
# • Persistance : remplacer la graine par une base SQLite (module sqlite3) ou
#   une base MySQL de la DSI ; chaque accès à ss.dossiers devient une requête.
# • Notifications : envoi d'e-mails (smtplib) ou WhatsApp Business API à
#   chaque nouvelle décision / relance (aucun membre ne ratera son tour).
# • Vraie IA : brancher un LLM (Mistral / OpenAI / Gemini) dans les fonctions
#   ia_*() pour des résumés et brouillons plus nuancés ; ajouter l'OCR pour
#   extraire automatiquement les données des fiches techniques PDF (devis,
#   certificats) : st.file_uploader + pymupdf.
# • Sécurité : SSO LDAP de l'université + journal d'audit (qui a voté, quand).
# • Signature électronique des PV (nées d'agrément : e-signature cohérente).
# ============================================================================

# ============================================================================
# 11) POINT D'ENTRÉE
# ============================================================================
def main():
    initialiser_donnees()
    uid = ss.get("connecte_id")
    if not uid:
        page_connexion()
        return
    user = next(u for u in UTILISATEURS if u["id"] == uid)
    menu = barre_laterale(user)
    if ss.get("voir"):                    # vue dossier « overlay » : prioritaire
        page_detail(ss["voir"], user)
        return
    if menu == "🏠 Tableau de bord":
        page_tableau_bord(user)
    elif menu == "📋 Dossiers":
        page_dossiers(user)
    elif menu == "➕ Nouveau dossier":
        page_nouveau(user)
    elif menu == "✍️ Mes validations":
        page_mes_validations(user)
    elif menu == "🤖 Assistant IA":
        page_assistant(user)
    elif menu == "📄 Rapports & PV":
        page_rapports(user)


main()



