# Kindle Vocab to Anki

Plugin [calibre](https://calibre-ebook.com/) qui transforme le vocabulaire et les surlignages d'une Kindle en cartes
[Anki](https://apps.ankiweb.net/).

Il lit deux fichiers de la liseuse :

- `system/vocabulary/vocab.db` : les mots cherchés dans le dictionnaire, avec la phrase où ils apparaissent ;
- `documents/My Clippings.txt` : les surlignages et les notes.

## Fonctionnalités

**Onglet Vocabulaire**

- filtres par langue, livre, plage de dates et recherche ; colonnes triables ;
- traduction des mots cochés vers la langue de son choix, avec quatre sources au choix ;
- traductions modifiables à la main et mises en cache.

**Onglet Surlignages**

- filtres par livre et plage de dates, sélection par cases à cocher ;
- copie ou export en Markdown ;
- cartes « citation » : le passage au recto, le livre, la note et la référence au verso ;
- extraction par IA du vocabulaire et des tournures intéressantes, avec relecture avant export.

**Exports**

| Destination | Détail |
|---|---|
| Fichier `.apkg` | Paquet Anki avec son type de note, cartes dans un sens ou dans les deux |
| Fichier `.csv` | Texte importable par Anki, avec deck, étiquettes et identifiant anti-doublon |
| Téléphone (USB) | Copie par `adb` puis import validé automatiquement dans AnkiDroid |
| AnkiWeb | Ajout direct à la collection en ligne, sans passer par le téléphone |

Chaque note porte un identifiant stable : réexporter les mêmes mots ne crée pas de doublon.

## Sources de traduction

| Source | Réglage | Particularité |
|---|---|---|
| Wiktionnaire | aucun | Hors ligne, dictionnaires [WikDict](https://www.wikdict.com/) téléchargés à la demande ; ne tient pas compte de la phrase |
| DeepL | clé d'API | Un appel par mot, la phrase sert de contexte |
| Claude | clé d'API | Par lots, traduit le mot dans le sens qu'il a dans la phrase |
| Ollama | adresse et modèle | Local ; repasse mot par mot quand le modèle ne gère pas les lots |

L'extraction de flashcards depuis les surlignages demande un modèle de langue : Claude ou Ollama.

## Installation

Il faut calibre 7 ou plus récent, et rien d'autre.

1. Télécharger le fichier `kindle-vocab-anki-vX.Y.Z.zip` de la
   [dernière version](https://github.com/adrian3d/kindle-anki-vocabulary/releases/latest), sans le décompresser.
2. Dans calibre : Préférences → Extensions → « Charger une extension depuis un fichier », choisir ce fichier et
   accepter l'avertissement de sécurité.
3. Redémarrer calibre.
4. Si le bouton « Vocabulaire Kindle » n'apparaît pas, l'ajouter : Préférences → Barres d'outils et menus → La
   barre d'outils principale.

Le ZIP proposé par le bouton « Code » de GitHub n'est pas installable tel quel : le plugin s'y trouve dans un
sous-dossier.

### Depuis les sources

```bash
git clone https://github.com/adrian3d/kindle-anki-vocabulary.git
cd kindle-anki-vocabulary
calibre-customize -b plugin
```

### Publier une version

Mettre à jour `version` dans `plugin/__init__.py`, puis pousser une étiquette du même numéro :

```bash
git tag v1.0.1 && git push origin v1.0.1
```

GitHub Actions lance alors les tests, construit le fichier installable et publie la version.

## Utilisation

1. Brancher la Kindle : les deux fichiers sont détectés. Sinon, les choisir avec « Parcourir… ».
2. Filtrer, cocher les lignes voulues, traduire.
3. Exporter dans un fichier, vers le téléphone ou vers AnkiWeb.

Les clés d'API, le modèle Claude et le serveur Ollama se règlent dans « Préférences… », en bas de la fenêtre.

### Envoi au téléphone

Il faut `adb` sur l'ordinateur, le débogage USB activé sur le téléphone et AnkiDroid installé. La fenêtre d'envoi
liste les decks du téléphone et permet d'en créer un nouveau. Si un écran d'AnkiDroid n'est pas reconnu, l'import
reste ouvert sur le téléphone, à confirmer à la main.

### Envoi vers AnkiWeb

Au premier usage, le plugin télécharge les bibliothèques officielles Anki depuis PyPI (environ 12 Mo) dans son
dossier de données et les exécute avec le Python de calibre : rien d'autre n'est à installer. Chaque archive est
comparée à une empreinte inscrite dans le plugin.

Le mot de passe n'est pas conservé ; seul le jeton de session l'est. Si AnkiWeb réclame une synchronisation
complète, qui écraserait un côté, rien n'est envoyé.

## Données enregistrées

Dans le dossier de configuration de calibre, sous `plugins/` :

- `kindle_vocab_anki.json` : réglages, clés d'API et jeton AnkiWeb, **en clair** ;
- `kindle_vocab_anki/` : cache des traductions, dictionnaires, bibliothèques Anki et copie relais de la collection.

## Développement

Les modules sans dépendance à calibre (`vocab`, `clippings`, `translators`, `flashcards`, `apkg`, `phone`,
`ankiweb`, `cache`) se testent hors de calibre :

```bash
uv run --no-project --with pytest --with anki pytest tests
```

Les tests d'AnkiWeb lancent le serveur de synchronisation fourni par la bibliothèque `anki` ; sans elle, ils sont
ignorés. Après une modification, `calibre-customize -b plugin` réinstalle le plugin.

## Limites connues

- Seul le format anglais de `My Clippings.txt` est reconnu.
- Testé sous Linux, où calibre utilise le Python du système ; les versions Windows et macOS n'ont pas été essayées.
- L'envoi au téléphone dépend des écrans d'import d'AnkiDroid et peut demander une confirmation manuelle.
