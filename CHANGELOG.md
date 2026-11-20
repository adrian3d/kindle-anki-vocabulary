# Changelog

## v1.1.0 — 2026-11-20

### Nouveautés

- **Prononciation sur les cartes** : avec la case « Prononciation », chaque mot reçoit l'enregistrement de
  Wiktionary quand il existe, sinon la voix de synthèse de l'appareil qui affiche la carte. Le son passe par le
  `.apkg`, le téléphone et AnkiWeb (pas par le CSV). Un « Contact pour Wikimedia » se règle dans les préférences :
  sans lui, Wikimedia refuse une bonne partie des téléchargements.
- **Interface en anglais** : le plugin parle français quand calibre est en français, anglais sinon. La « Langue du
  plugin », dans les préférences, impose l'une ou l'autre.
- **Remplacer les cartes déjà présentes sur AnkiWeb** : une case de la fenêtre d'envoi fait prendre aux cartes déjà
  présentes le contenu envoyé (une meilleure traduction, la phrase, le son) et les range dans le deck choisi, en
  gardant leur historique de révision.
- **Réanalyser des surlignages** : la case « Réanalyser les passages déjà analysés » renvoie au modèle des passages
  dont les flashcards étaient en cache.
- **Cocher plus vite** : Maj+clic sur une case coche ou décoche toute la plage ; Espace et le clic droit cochent ou
  décochent les lignes sélectionnées.
- **Périodes de dates** : un bouton « Période » ramène le filtre à aujourd'hui, aux 7 ou 30 derniers jours, à
  l'année en cours, ou le supprime.

### Améliorations

- Les champs de date sont toujours actifs : changer une date coche la case correspondante, et le calendrier s'ouvre
  sur le mois du dernier élément affiché plutôt que sur le premier, des années plus tôt.
- Une barre animée, un message ou un curseur d'attente signale chaque opération longue : envoi au téléphone ou vers
  AnkiWeb, recherche du téléphone, premier téléchargement d'un dictionnaire, extraction par IA, liste des modèles
  Ollama.
- Dans l'onglet Surlignages, la ligne des flashcards par IA passe au-dessus de la ligne d'export.

### Corrections

- L'extraction par IA ne traduit plus le recto des flashcards : le modèle doit recopier l'extrait exact du passage,
  et une carte dont l'extrait est introuvable est écartée. Changer le prompt relance l'analyse des passages.
- Un envoi vers AnkiWeb annonçait un succès alors que les cartes, déjà présentes avec l'ancien type de note,
  n'étaient pas importées. Le compte rendu distingue maintenant les notes ajoutées, remplacées et laissées telles
  quelles.

### À savoir

- Les cartes avec son utilisent un nouveau type de note, « Kindle vocabulary (audio) ». Les cartes déjà importées
  avec l'ancien type ne reçoivent le son que si elles sont remplacées, et perdent alors leur historique.
- Avec Ollama, l'extraction de flashcards demande un modèle généraliste (gemma3, qwen3…) plutôt qu'un modèle de
  traduction.

## v1.0.0 — 2026-11-19

Première version : vocabulaire et surlignages de la Kindle, traduction (Wiktionnaire, DeepL, Claude, Ollama),
flashcards extraites des surlignages par IA, export `.apkg` et CSV, envoi au téléphone et vers AnkiWeb.
