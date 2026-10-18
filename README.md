# 🏥 FMPA VALID — Validation asynchrone des dossiers d'achats

Application Streamlit pour le **Service des Marchés de la Faculté de Médecine et de Pharmacie d'Agadir (FMPA)** :
permettre à la commission d'achat (Professeurs + Médecins) de **valider les dossiers en différé**,
sans réunion physique — sauf en cas d'« avis partagés ».

## 🤖 Ce que fait l'IA

| # | Fonction | Où dans l'app |
|---|----------|---------------|
| 1 | Résumé exécutif de chaque dossier | Détail du dossier → onglet « Résumé & priorité » |
| 2 | Score de conformité réglementaire /100 (6 contrôles) | Détail du dossier → onglet « Conformité » |
| 3 | Détection d'anomalies (montants, procédures, incohérences) | Détail + argumentaire du débat |
| 4 | Priorisation automatique 🥇🥈🥉 | Tableau de bord, listes, tri |
| 5 | Justification technique pré-rédigée | Nouveau dossier |
| 6 | Brouillons d'avis + chatbot « répondeur de commission » | Détail (membre) + Assistant IA |
| 7 | Génération automatique du PV de séance | Rapports & PV |

## ⚙️ Écrans

- **🏠 Tableau de bord** : indicateurs, graphiques, priorités IA, échéances
- **📋 Dossiers** : liste filtrable, tri par priorité IA
- **✍️ Mes validations** (membres) : file d'avis en attente, brouillons IA
- **➕ Nouveau dossier** (admin) : aperçu IA en direct
- **🤖 Assistant IA** : chatbot sur les dossiers
- **📄 Rapports & PV** : PV automatique + export CSV

## 🚀 Lancement

```bash
pip install streamlit pandas
streamlit run app_fmpa.py
```

## 👤 Profils de démonstration

- **Mme R. Fadili** — Administrateur (crée les dossiers, clôture, génère le PV)
- **Pr. A. Bennani, Pr. S. Chraibi, Dr. M. Tahiri, Pr. N. El Fassi** — Membres de la commission

> Projet pédagogique : données fictives stockées en session. En production :
> SSO/LDAP de l'université + base de données (SQLite/MySQL) + notifications e-mail.
