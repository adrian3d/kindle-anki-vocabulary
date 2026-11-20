_state = {'language': 'fr'}


def resolve(setting, interface_language):
    if setting in ('fr', 'en'):
        return setting
    return 'fr' if (interface_language or '').lower().startswith('fr') else 'en'


def set_language(language):
    _state['language'] = 'en' if language == 'en' else 'fr'


def N_(text):
    return text


def _(text):
    # Les textes du plugin sont écrits en français : ils servent eux-mêmes de clés au catalogue anglais.
    return ENGLISH.get(text, text) if _state['language'] == 'en' else text


def language_label(english_name):
    return FRENCH_LANGUAGE_NAMES.get(english_name, english_name) if _state['language'] == 'fr' else english_name


FRENCH_LANGUAGE_NAMES = {
    'French': 'Français', 'English': 'Anglais', 'Spanish': 'Espagnol', 'German': 'Allemand', 'Italian': 'Italien',
    'Portuguese': 'Portugais', 'Dutch': 'Néerlandais', 'Swedish': 'Suédois', 'Norwegian': 'Norvégien',
    'Danish': 'Danois', 'Finnish': 'Finnois', 'Polish': 'Polonais', 'Russian': 'Russe', 'Greek': 'Grec',
    'Turkish': 'Turc', 'Japanese': 'Japonais', 'Chinese': 'Chinois', 'Catalan': 'Catalan', 'Latin': 'Latin',
}

ENGLISH = {
    'Vocabulaire Kindle':
        'Kindle Vocabulary',
    'Vocabulaire et surlignages de la Kindle vers Anki et Markdown':
        'Kindle vocabulary and highlights to Anki and Markdown',
    'Les bibliothèques Anki ne sont pas installées.':
        'The Anki libraries are not installed.',
    "Le fichier « {name} » ne correspond pas à l'empreinte attendue : installation annulée.":
        'The file "{name}" does not match the expected checksum: installation cancelled.',
    "La synchronisation s'est arrêtée sans réponse : {error}":
        'The sync stopped without an answer: {error}',
    'Téléchargement des bibliothèques Anki ({index}/{total})…':
        'Downloading the Anki libraries ({index}/{total})…',
    'Installation des bibliothèques Anki impossible : {error}':
        'Could not install the Anki libraries: {error}',
    'Aucune version de « {name} » pour ce système ({platform}).':
        'No version of "{name}" for this system ({platform}).',
    'Téléchargement de « {name} » impossible : {error}':
        'Could not download "{name}": {error}',
    'Lancement de la synchronisation impossible : {error}':
        'Could not start the sync: {error}',
    'AnkiWeb a refusé les identifiants. Reconnectez-vous.':
        'AnkiWeb rejected the credentials. Please log in again.',
    'Ajout des cartes…':
        'Adding the cards…',
    'Envoi vers AnkiWeb…':
        'Uploading to AnkiWeb…',
    'Récupération de la collection AnkiWeb…':
        'Fetching the AnkiWeb collection…',
    "AnkiWeb demande une synchronisation complète, qui écraserait un côté. Rien n'a été envoyé : synchronisez d'abord vos appareils, puis réessayez.":
        'AnkiWeb asks for a full sync, which would overwrite one side. Nothing was sent: sync your devices first, then try again.',
    'Envoi des prononciations vers AnkiWeb…':
        'Uploading the pronunciations to AnkiWeb…',
    'emp. {location}':
        'loc. {location}',
    '**Note** : {note}':
        '**Note**: {note}',
    '**Note** ({reference}) : {note}':
        '**Note** ({reference}): {note}',
    'Wiktionnaire (hors ligne)':
        'Wiktionary (offline)',
    'Ollama (local)':
        'Ollama (local)',
    'Comme calibre':
        'Same as calibre',
    'Adresse e-mail ou page web':
        'Email address or web page',
    'Lister les modèles':
        'List models',
    'Langue du plugin':
        'Plugin language',
    "Prise en compte à la prochaine ouverture de la fenêtre ; le bouton de la barre d'outils change au redémarrage de calibre.":
        'Applied the next time the window opens; the toolbar button changes when calibre restarts.',
    "Clé d'API Claude":
        'Claude API key',
    'Modèle Claude':
        'Claude model',
    "Clé d'API DeepL":
        'DeepL API key',
    "Adresse d'Ollama":
        'Ollama address',
    'Modèle Ollama':
        'Ollama model',
    'Contact pour Wikimedia':
        'Contact for Wikimedia',
    'Les prononciations viennent de Wikimedia, qui refuse souvent les téléchargements des programmes sans contact : ce contact est joint à chaque requête.':
        'Pronunciations come from Wikimedia, which often refuses downloads from programs that give no contact: this contact is sent with every request.',
    'Recherche des modèles…':
        'Looking for models…',
    'Les clés sont enregistrées en clair dans le dossier de configuration de calibre.':
        "Keys are stored in plain text in calibre's configuration folder.",
    '{count} modèle(s) installé(s)':
        '{count} model(s) installed',
    'Mot':
        'Word',
    'Forme de base':
        'Base form',
    'Traduction':
        'Translation',
    'Ajouté le':
        'Added on',
    'Livre':
        'Book',
    'Phrase':
        'Sentence',
    'Date':
        'Date',
    'Référence':
        'Reference',
    'Texte':
        'Text',
    'Note':
        'Note',
    'Type':
        'Type',
    'Recto':
        'Front',
    'Verso':
        'Back',
    'Remarque':
        'Comment',
    'Passage':
        'Passage',
    'Vocabulaire':
        'Vocabulary',
    'Tournure':
        'Expression',
    'Envoyer au téléphone':
        'Send to phone',
    'Envoyer vers AnkiWeb':
        'Send to AnkiWeb',
    'Paquet Anki (.apkg)':
        'Anki package (.apkg)',
    'CSV pour Anki (.csv)':
        'CSV for Anki (.csv)',
    'Opération en cours…':
        'Working…',
    'Branchez la Kindle ou choisissez le fichier':
        'Plug in the Kindle or choose the file',
    'Parcourir…':
        'Browse…',
    'Choisir le fichier':
        'Choose the file',
    'Du':
        'From',
    'Au':
        'To',
    'Deck de destination':
        'Destination deck',
    'Créer un nouveau deck nommé :':
        'Create a new deck named:',
    'Par exemple : Anglais::Siege and Storm (« :: » crée un sous-deck)':
        'For example: English::Siege and Storm ("::" creates a subdeck)',
    'Cartes dans les deux sens':
        'Cards in both directions',
    'Envoyer':
        'Send',
    'Fermer':
        'Close',
    'AnkiDroid, par le câble USB':
        'AnkiDroid, over the USB cable',
    'Ajouter à un deck existant du téléphone :':
        'Add to an existing deck on the phone:',
    'Actualiser':
        'Refresh',
    'Recherche du téléphone…':
        'Looking for the phone…',
    'Préparation du paquet…':
        'Preparing the package…',
    'votre compte AnkiWeb, directement depuis cet ordinateur':
        'your AnkiWeb account, straight from this computer',
    'Ajouter à un deck existant du compte :':
        'Add to an existing deck of the account:',
    'Adresse e-mail du compte AnkiWeb':
        'AnkiWeb account email address',
    'Mot de passe (non conservé)':
        'Password (not stored)',
    'Compte AnkiWeb':
        'AnkiWeb account',
    "Les cartes sont ajoutées à votre collection en ligne ; vos appareils les reçoivent à leur prochaine synchronisation. Au premier usage, le plugin télécharge une fois les bibliothèques officielles Anki (environ 12 Mo) dans son dossier de données ; rien d'autre n'est à installer.":
        'Cards are added to your online collection; your devices get them at their next sync. On first use, the plugin downloads the official Anki libraries once (about 12 MB) into its data folder; nothing else needs installing.',
    'Connexion à AnkiWeb…':
        'Connecting to AnkiWeb…',
    'Paquet .apkg uniquement : en CSV, le sens des cartes dépend du type de note choisi dans Anki.':
        '.apkg package only: with CSV, card directions depend on the note type chosen in Anki.',
    'Prononciation':
        'Pronunciation',
    "Paquet .apkg, téléphone et AnkiWeb : enregistrement de Wiktionary quand il existe, sinon voix de synthèse de l'appareil qui affiche la carte.":
        '.apkg package, phone and AnkiWeb: a Wiktionary recording when one exists, otherwise the text-to-speech voice of the device showing the card.',
    'Exporter…':
        'Export…',
    'Envoyer au téléphone…':
        'Send to phone…',
    "Ouvre une fenêtre pour choisir le deck sur le téléphone et lancer l'envoi par USB.":
        'Opens a window to choose the deck on the phone and send over USB.',
    'Envoyer vers AnkiWeb…':
        'Send to AnkiWeb…',
    'Ouvre une fenêtre pour envoyer les cartes dans votre compte AnkiWeb, sans passer par le téléphone.':
        'Opens a window to send the cards to your AnkiWeb account, without going through the phone.',
    'Exporter pour Anki':
        'Export for Anki',
    'Export Anki':
        'Anki export',
    'Traduction en cours…':
        'Translating…',
    'Flashcards extraites des surlignages':
        'Flashcards extracted from highlights',
    'Rechercher un mot':
        'Search for a word',
    'Remplacer les traductions existantes':
        'Replace existing translations',
    'Traduire les mots cochés':
        'Translate checked words',
    'Toutes les langues':
        'All languages',
    'Tous les livres':
        'All books',
    'Annuler':
        'Cancel',
    'Réanalyser les passages déjà analysés':
        'Analyze already analyzed passages again',
    'Extraire vocabulaire et tournures…':
        'Extract vocabulary and expressions…',
    'Analyse des surlignages…':
        'Analyzing highlights…',
    'Exporter les surlignages':
        'Export highlights',
    'Surlignages Kindle':
        'Kindle highlights',
    'Vocabulaire et surlignages Kindle':
        'Kindle vocabulary and highlights',
    'Surlignages':
        'Highlights',
    '{count} note(s) à envoyer vers {destination}.':
        '{count} note(s) to send to {destination}.',
    'Opération en cours : patientez avant de fermer.':
        'Operation in progress: wait before closing.',
    "Le paquet est ouvert dans AnkiDroid, mais la validation automatique n'a pas abouti : confirmez l'import sur le téléphone.":
        'The package is open in AnkiDroid, but the automatic confirmation failed: confirm the import on the phone.',
    'Se connecter':
        'Log in',
    'Se déconnecter':
        'Log out',
    'Non connecté.':
        'Not logged in.',
    "Saisissez l'adresse e-mail et le mot de passe du compte AnkiWeb.":
        'Enter the email address and password of the AnkiWeb account.',
    '{count} nouvelle(s) note(s) ajoutée(s) au deck « {deck} » sur AnkiWeb.':
        '{count} new note(s) added to the "{deck}" deck on AnkiWeb.',
    'Synchronisez AnkiDroid pour les recevoir.':
        'Sync AnkiDroid to get them.',
    'Rien à exporter : il faut un nom de deck et au moins une ligne cochée exportable.':
        'Nothing to export: you need a deck name and at least one checked, exportable row.',
    '{count} note(s) exportée(s) dans {path}.':
        '{count} note(s) exported to {path}.',
    'Rien à envoyer : cochez au moins une ligne exportable.':
        'Nothing to send: check at least one exportable row.',
    'Base de vocabulaire Kindle':
        'Kindle vocabulary database',
    'Tout cocher':
        'Check all',
    'Tout décocher':
        'Uncheck all',
    'Traduire vers':
        'Translate to',
    'avec':
        'with',
    'Aucun mot coché à traduire.':
        'No checked word to translate.',
    'Copier en Markdown':
        'Copy as Markdown',
    'Exporter en Markdown…':
        'Export as Markdown…',
    'Flashcards par IA : ma langue':
        'AI flashcards: my language',
    'Aucun surlignage coché.':
        'No highlight checked.',
    "Le modèle n'a rien trouvé à mettre en carte dans ces passages.":
        'The model found nothing worth a card in these passages.',
    'Préférences…':
        'Preferences…',
    "Lecture des decks d'AnkiDroid…":
        'Reading AnkiDroid decks…',
    '{count} deck(s) dans la collection AnkiWeb.':
        '{count} deck(s) in the AnkiWeb collection.',
    'Exporter dans un fichier : deck':
        'Export to a file: deck',
    '{count} carte(s) : {vocabulary} de vocabulaire, {expressions} tournure(s). Décochez celles à écarter ; recto, verso et remarque sont modifiables.':
        '{count} card(s): {vocabulary} vocabulary, {expressions} expression(s). Uncheck the ones to drop; front, back and comment can be edited.',
    '{checked} mot(s) coché(s) sur {total}, dont {translated} traduit(s)':
        '{checked} of {total} word(s) checked, {translated} translated',
    '{count} passage(s) copié(s) dans le presse-papiers':
        '{count} passage(s) copied to the clipboard',
    '{count} passage(s) exporté(s) dans {path}.':
        '{count} passage(s) exported to {path}.',
    'Erreur inattendue : {error}':
        'Unexpected error: {error}',
    'Prononciations Wiktionary : {done}/{total}…':
        'Wiktionary pronunciations: {done}/{total}…',
    '{count} ligne(s) cochée(s) sans contenu exportable sont laissées de côté.':
        '{count} checked row(s) with nothing to export are left out.',
    'Échec : {error}':
        'Failed: {error}',
    'Téléphone {serial} connecté, {count} deck(s) dans AnkiDroid.':
        'Phone {serial} connected, {count} deck(s) in AnkiDroid.',
    'Téléphone non disponible. {error}':
        'Phone not available. {error}',
    '{count} note(s) importée(s) dans le deck « {deck} » du téléphone.':
        '{count} note(s) imported into the "{deck}" deck on the phone.',
    'Connecté en tant que {user}.':
        'Logged in as {user}.',
    'Écriture impossible : {error}':
        'Could not write the file: {error}',
    '{count} ligne(s) cochée(s) sans contenu exportable ont été ignorée(s).':
        '{count} checked row(s) with nothing to export were skipped.',
    'Téléchargement du dictionnaire {source} → {target}…':
        'Downloading the {source} → {target} dictionary…',
    '{checked} passage(s) coché(s) sur {shown} affiché(s), {total} au total':
        '{checked} of {shown} shown passage(s) checked, {total} in total',
    'Analyse des surlignages : {done}/{total} passage(s)…':
        'Analyzing highlights: {done}/{total} passage(s)…',
    'Impossible de lire {path} : {error}':
        'Could not read {path}: {error}',
    '{count} mots vont être envoyés à {service}, un service payant. Continuer ?':
        '{count} words will be sent to {service}, a paid service. Continue?',
    '{count} passages vont être envoyés à {service}, un service payant. Continuer ?':
        '{count} passages will be sent to {service}, a paid service. Continue?',
    'La commande « adb » est introuvable : installez les outils Android (paquet android-tools-adb).':
        'The "adb" command was not found: install the Android tools (android-tools-adb package).',
    'Aucun téléphone détecté : branchez-le en USB et activez le débogage USB.':
        'No phone detected: plug it in over USB and enable USB debugging.',
    'Copie du paquet sur le téléphone…':
        'Copying the package to the phone…',
    "Android n'a pas indexé le paquet copié : import impossible.":
        'Android did not index the copied package: import impossible.',
    "Validation de l'import…":
        'Confirming the import…',
    'Import en cours…':
        'Importing…',
    "Le téléphone est branché mais n'a pas autorisé le débogage USB : acceptez la demande à l'écran.":
        'The phone is plugged in but has not allowed USB debugging: accept the prompt on its screen.',
    'Collection AnkiDroid introuvable sur le téléphone.':
        'AnkiDroid collection not found on the phone.',
    "Le téléphone est verrouillé : déverrouillez-le puis relancez l'envoi.":
        'The phone is locked: unlock it, then send again.',
    "AnkiDroid n'est pas installé sur le téléphone.":
        'AnkiDroid is not installed on the phone.',
    "Ouverture de l'import dans AnkiDroid…":
        'Opening the import in AnkiDroid…',
    'adb {command} a échoué : {error}':
        'adb {command} failed: {error}',
    'Wiktionnaire':
        'Wiktionary',
    "Claude : clé d'API manquante (Préférences du plugin)":
        'Claude: API key missing (plugin Preferences)',
    'Claude : requête refusée par le modèle':
        'Claude: request refused by the model',
    'Claude : réponse tronquée, réduisez la sélection':
        'Claude: answer cut off, select fewer items',
    'Ollama : aucun modèle choisi (Préférences du plugin)':
        'Ollama: no model chosen (plugin Preferences)',
    "DeepL : clé d'API manquante (Préférences du plugin)":
        'DeepL: API key missing (plugin Preferences)',
    '{service} : réponse JSON inattendue':
        '{service}: unexpected JSON answer',
    '{service} : HTTP {code} — {message}':
        '{service}: HTTP {code} — {message}',
    '{service} : connexion impossible à {url} ({error})':
        '{service}: could not connect to {url} ({error})',
    '{service} : réponse illisible':
        '{service}: unreadable answer',
    'Wiktionnaire : téléchargement impossible (HTTP {code})':
        'Wiktionary: download failed (HTTP {code})',
    'Wiktionnaire : téléchargement impossible ({error})':
        'Wiktionary: download failed ({error})',
    'Wiktionnaire : pas de dictionnaire {source} → {target}':
        'Wiktionary: no {source} → {target} dictionary',
    "Aujourd'hui":
        'Today',
    '7 derniers jours':
        'Last 7 days',
    '30 derniers jours':
        'Last 30 days',
    'Cette année':
        'This year',
    'Toutes les dates':
        'All dates',
    'Période':
        'Period',
    'Cocher les lignes sélectionnées':
        'Check selected rows',
    'Décocher les lignes sélectionnées':
        'Uncheck selected rows',
    'Maj+clic sur une case coche ou décoche toute la plage. Espace, ou le clic droit, coche ou décoche les lignes sélectionnées (Maj, Ctrl, Ctrl+A).':
        'Shift+click on a box checks or unchecks the whole range. Space, or a right click, checks or unchecks the selected rows (Shift, Ctrl, Ctrl+A).',
    'Remplacer les cartes déjà présentes':
        'Replace cards already there',
    "Les cartes déjà dans la collection prennent le contenu envoyé (traduction, phrase, son) et rejoignent le deck choisi, en gardant leur historique de révision. Celles d'un ancien type de note, sans son, sont recréées et perdent leur historique.":
        'Cards already in the collection take the content being sent (translation, sentence, sound) and move to the chosen deck, keeping their review history. Those of an older note type, without sound, are created again and lose their history.',
    '{count} carte(s) déjà présente(s) remplacée(s) par la nouvelle version.':
        '{count} card(s) already there replaced by the new version.',
    "Dont {count} d'un ancien type de note, recréée(s) sans leur historique.":
        'Including {count} of an older note type, created again without their history.',
    '{count} déjà présente(s), laissée(s) telle(s) quelle(s) : cochez « Remplacer les cartes déjà présentes » pour les mettre à jour.':
        '{count} already there, left as they were: check "Replace cards already there" to update them.',
}
