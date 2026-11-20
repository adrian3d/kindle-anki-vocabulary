import hashlib
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import replace

from calibre.gui2 import choose_files, choose_save_file, error_dialog, info_dialog, question_dialog
from qt.core import (
    QApplication, QCheckBox, QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox, QEvent, QHBoxLayout, QHeaderView,
    QGroupBox, QLabel, QLineEdit, QProgressBar, QProgressDialog, QPushButton, QRadioButton, Qt, QTableWidget, QTableWidgetItem, QTabWidget, QThread,
    QVBoxLayout, QWidget, pyqtSignal,
)

from calibre_plugins.kindle_vocab_anki import ankiweb, apkg, clippings, flashcards, phone, translators, vocab
from calibre_plugins.kindle_vocab_anki.i18n import N_, _, language_label
from calibre_plugins.kindle_vocab_anki.config import (
    LLM_PROVIDERS, PROVIDERS, make_ankiweb, make_cache, make_pronunciations, make_translator, prefs,
)

CONFIRMATION_THRESHOLD = 200
PAID_PROVIDERS = ('claude', 'deepl')
READ_ONLY = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
KEY_ROLE = Qt.ItemDataRole.UserRole

COL_CHECK, COL_WORD, COL_STEM, COL_TRANSLATION, COL_DATE, COL_BOOK, COL_USAGE = range(7)
VOCAB_COLUMNS = ('', N_('Mot'), N_('Forme de base'), N_('Traduction'), N_('Ajouté le'), N_('Livre'), N_('Phrase'))
HIGHLIGHT_COLUMNS = ('', N_('Date'), N_('Livre'), N_('Référence'), N_('Texte'), N_('Note'))
HIGHLIGHT_CHECK, HIGHLIGHT_TEXT = 0, 4
CARD_COLUMNS = ('', N_('Type'), N_('Recto'), N_('Verso'), N_('Remarque'), N_('Passage'))
CARD_CHECK, CARD_KIND, CARD_FRONT, CARD_BACK, CARD_NOTE, CARD_SENTENCE = range(6)
KIND_LABELS = {'vocabulary': N_('Vocabulaire'), 'expression': N_('Tournure')}
EXPORT_FORMATS = (('apkg', N_('Paquet Anki (.apkg)')), ('csv', N_('CSV pour Anki (.csv)')))


class SourceRow(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, label, dialog_name, file_filter, path):
        super().__init__()
        self.dialog_name, self.file_filter = dialog_name, file_filter
        self.path = QLineEdit(path)
        self.path.setReadOnly(True)
        self.path.setPlaceholderText(_('Branchez la Kindle ou choisissez le fichier'))
        browse = QPushButton(_('Parcourir…'))
        browse.clicked.connect(self.browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))
        layout.addWidget(self.path, 1)
        layout.addWidget(browse)

    def browse(self):
        files = choose_files(self, self.dialog_name, _('Choisir le fichier'), filters=[self.file_filter], select_only_single_file=True)
        if files:
            self.path.setText(files[0])
            self.changed.emit(files[0])


class DateRange(QWidget):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.latest, self.calendars = None, []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.start_enabled, self.start = self._add_bound(layout, _('Du'))
        self.end_enabled, self.end = self._add_bound(layout, _('Au'))

    def _add_bound(self, layout, label):
        enabled, edit = QCheckBox(label), QDateEdit(QDate.currentDate())
        edit.setCalendarPopup(True)
        edit.setDisplayFormat('dd/MM/yyyy')
        calendar = edit.calendarWidget()
        calendar.installEventFilter(self)
        self.calendars.append((calendar, enabled))
        enabled.toggled.connect(lambda _checked: self.changed.emit())
        edit.dateChanged.connect(lambda _date: self._on_date_changed(enabled))
        layout.addWidget(enabled)
        layout.addWidget(edit)
        return enabled, edit

    def _on_date_changed(self, enabled):
        if enabled.isChecked():
            self.changed.emit()
        else:
            enabled.setChecked(True)

    def eventFilter(self, watched, event):
        # Le calendrier s'ouvre sur la date du champ, souvent le premier surlignage, des années plus tôt.
        if event.type() == QEvent.Type.Show and self.latest:
            for calendar, enabled in self.calendars:
                if calendar is watched and not enabled.isChecked():
                    calendar.setCurrentPage(self.latest.year, self.latest.month)
        return False

    def bounds(self):
        return (
            self.start.date().toPyDate() if self.start_enabled.isChecked() else None,
            self.end.date().toPyDate() if self.end_enabled.isChecked() else None,
        )

    def set_span(self, first, last):
        self.latest = last
        for enabled, edit, value in ((self.start_enabled, self.start, first), (self.end_enabled, self.end, last)):
            if value and not enabled.isChecked():
                edit.blockSignals(True)
                edit.setDate(QDate(value.year, value.month, value.day))
                edit.blockSignals(False)


def make_table(columns, stretch_column):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([_(column) for column in columns])
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    return table


@contextmanager
def busy_cursor():
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def make_close_buttons():
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    # Qt traduit ses boutons standard dans la langue de calibre, qui peut différer de celle choisie pour le plugin.
    buttons.button(QDialogButtonBox.StandardButton.Close).setText(_('Fermer'))
    return buttons


def make_cell(text, flags=READ_ONLY):
    cell = QTableWidgetItem(text)
    cell.setFlags(flags)
    cell.setToolTip(text)
    return cell


def fill_combo(combo, all_label, entries):
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(all_label, None)
    for value, label in entries:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(combo.findData(current), 0))
    combo.blockSignals(False)


class TaskWorker(QThread):
    step = pyqtSignal(str)
    done = pyqtSignal(object, str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self):
        result, error = None, ''
        try:
            result = self.task(self.step.emit)
        except (phone.PhoneError, ankiweb.AnkiWebError, OSError) as exception:
            error = str(exception)
        except Exception as exception:
            error = _('Erreur inattendue : {error}').format(error=exception)
        self.done.emit(result, error)


def write_package(path, deck, notes, reverse, audio, on_step):
    if not audio:
        apkg.write_apkg(path, deck, [replace(note, lang='', audio='') for note in notes], reverse)
        return False
    pronunciations = make_pronunciations()
    files = pronunciations.fetch_all(
        ((note.word, note.lang) for note in notes if not note.passage),
        lambda done, total: on_step(_('Prononciations Wiktionary : {done}/{total}…').format(done=done, total=total)),
    )
    notes = [replace(note, audio=files.get((note.word, note.lang), '')) for note in notes]
    apkg.write_apkg(path, deck, notes, reverse, media_dir=pronunciations.directory)
    return any(note.audio for note in notes)


def with_temporary_package(deck, notes, reverse, audio, on_step, use):
    handle, path = tempfile.mkstemp(suffix='.apkg')
    os.close(handle)
    try:
        has_media = write_package(path, deck, notes, reverse, audio, on_step)
        return use(path, has_media)
    finally:
        os.remove(path)


class DeckChooser(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, existing_label):
        super().__init__(_('Deck de destination'))
        self.existing_choice = QRadioButton(existing_label)
        self.existing_deck = QComboBox()
        self.new_choice = QRadioButton(_('Créer un nouveau deck nommé :'))
        self.new_deck = QLineEdit(prefs['deck_name'])
        self.new_deck.setPlaceholderText(_('Par exemple : Anglais::Siege and Storm (« :: » crée un sous-deck)'))
        self.new_choice.setChecked(True)
        self.existing_choice.toggled.connect(self.on_changed)
        self.existing_deck.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self.new_deck.textChanged.connect(lambda _text: self.changed.emit())
        self.new_deck.textEdited.connect(lambda _text: self.new_choice.setChecked(True))
        layout = QVBoxLayout(self)
        for widget in (self.existing_choice, self.existing_deck, self.new_choice, self.new_deck):
            layout.addWidget(widget)
        self.set_decks([])

    def set_decks(self, decks):
        self.existing_deck.clear()
        self.existing_deck.addItems(decks)
        self.existing_choice.setEnabled(bool(decks))
        remembered = self.existing_deck.findText(prefs['deck_name'])
        if remembered >= 0:
            self.existing_deck.setCurrentIndex(remembered)
            self.existing_choice.setChecked(True)
            self.new_deck.clear()
        elif not decks:
            self.new_choice.setChecked(True)
        self.on_changed()

    def on_changed(self):
        self.existing_deck.setEnabled(self.existing_choice.isChecked() and self.existing_choice.isEnabled())
        self.changed.emit()

    def deck_name(self):
        if self.existing_choice.isChecked():
            return self.existing_deck.currentText().strip()
        return self.new_deck.text().strip()


class SendDialog(QDialog):
    title = ''

    def __init__(self, parent, notes, skipped, reverse_allowed, audio, destination, existing_label):
        super().__init__(parent)
        self.notes, self.worker, self.reverse_allowed, self.audio = notes, None, reverse_allowed, audio
        self.setWindowTitle(_(self.title))
        self.setMinimumWidth(580)

        summary = _('{count} note(s) à envoyer vers {destination}.').format(count=len(notes), destination=_(destination))
        if skipped:
            summary += ' ' + _('{count} ligne(s) cochée(s) sans contenu exportable sont laissées de côté.').format(count=skipped)
        self.summary = QLabel(summary)
        self.summary.setWordWrap(True)

        self.chooser = DeckChooser(_(existing_label))
        self.chooser.changed.connect(self.update_state)
        self.reverse = QCheckBox(_('Cartes dans les deux sens'))
        self.reverse.setChecked(prefs['reverse'] and reverse_allowed)
        self.reverse.setVisible(reverse_allowed)

        self.progress = QLabel('')
        self.progress.setWordWrap(True)
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumWidth(120)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.hide()
        self.send_button = QPushButton(_('Envoyer'))
        self.send_button.setDefault(True)
        self.send_button.clicked.connect(self.send)
        close = QPushButton(_('Fermer'))
        close.clicked.connect(self.reject)
        self.buttons = QHBoxLayout()
        self.buttons.addWidget(self.progress, 1)
        self.buttons.addWidget(self.busy_bar)
        self.buttons.addWidget(self.send_button)
        self.buttons.addWidget(close)

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def can_send(self):
        return True

    def update_state(self):
        self.send_button.setEnabled(self.can_send() and bool(self.chooser.deck_name()) and not self.busy())

    def run(self, task, on_done, message=N_('Opération en cours…')):
        self.worker = TaskWorker(task)
        self.worker.step.connect(self.progress.setText)
        self.worker.done.connect(lambda result, error: self.finish(result, error, on_done))
        self.progress.setText(_(message))
        self.busy_bar.show()
        self.worker.start()
        self.update_state()

    def finish(self, result, error, on_done):
        self.busy_bar.hide()
        self.progress.setText(_('Échec : {error}').format(error=error) if error else '')
        if not error:
            on_done(result)
        self.update_state()

    def remember(self, deck):
        prefs['deck_name'] = deck
        if self.reverse_allowed:
            prefs['reverse'] = self.reverse.isChecked()

    def reject(self):
        if self.busy():
            self.progress.setText(_('Opération en cours : patientez avant de fermer.'))
            return
        super().reject()


class PhoneDialog(SendDialog):
    title = N_('Envoyer au téléphone')

    def __init__(self, parent, notes, skipped, reverse_allowed=True, audio=False):
        super().__init__(parent, notes, skipped, reverse_allowed, audio, N_('AnkiDroid, par le câble USB'),
                         N_('Ajouter à un deck existant du téléphone :'))
        self.connected = False
        self.phone_status = QLabel('')
        self.phone_status.setWordWrap(True)
        self.refresh_button = QPushButton(_('Actualiser'))
        self.refresh_button.clicked.connect(self.load_decks)
        phone_row = QHBoxLayout()
        phone_row.addWidget(self.phone_status, 1)
        phone_row.addWidget(self.refresh_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addLayout(phone_row)
        layout.addWidget(self.chooser)
        layout.addWidget(self.reverse)
        layout.addLayout(self.buttons)
        self.load_decks()

    def can_send(self):
        return self.connected

    def update_state(self):
        super().update_state()
        self.refresh_button.setEnabled(not self.busy())

    def load_decks(self):
        if self.busy():
            return
        self.connected = False
        self.phone_status.setText(_('Recherche du téléphone…'))

        def task(on_step):
            try:
                device = phone.connect()
                on_step(_('Lecture des decks d\'AnkiDroid…'))
                return device.serial, device.list_decks(), ''
            except phone.PhoneError as error:
                return None, [], str(error)

        self.run(task, self.on_decks, N_('Recherche du téléphone…'))

    def on_decks(self, result):
        serial, decks, error = result
        self.connected = serial is not None
        if self.connected:
            self.phone_status.setText(_('Téléphone {serial} connecté, {count} deck(s) dans AnkiDroid.').format(serial=serial, count=len(decks)))
        else:
            self.phone_status.setText(_('Téléphone non disponible. {error}').format(error=error))
        self.chooser.set_decks(decks)

    def send(self):
        deck, reverse = self.chooser.deck_name(), self.reverse.isChecked()
        self.remember(deck)
        self.run(
            lambda on_step: with_temporary_package(
                deck, self.notes, reverse, self.audio, on_step,
                lambda path, _has_media: phone.connect().send_package(path, on_step)),
            lambda outcome: self.on_sent(deck, outcome),
            N_('Préparation du paquet…'),
        )

    def on_sent(self, deck, outcome):
        if outcome == phone.NEEDS_CONFIRMATION:
            self.progress.setText(_('Le paquet est ouvert dans AnkiDroid, mais la validation automatique n\'a pas abouti : '
                                    'confirmez l\'import sur le téléphone.'))
        else:
            self.progress.setText(_('{count} note(s) importée(s) dans le deck « {deck} » du téléphone.').format(count=len(self.notes), deck=deck))


class AnkiWebDialog(SendDialog):
    title = N_('Envoyer vers AnkiWeb')

    def __init__(self, parent, notes, skipped, reverse_allowed=True, audio=False):
        super().__init__(parent, notes, skipped, reverse_allowed, audio, N_('votre compte AnkiWeb, directement depuis cet ordinateur'),
                         N_('Ajouter à un deck existant du compte :'))
        self.client = make_ankiweb()

        self.account_status = QLabel('')
        self.account_status.setWordWrap(True)
        self.username = QLineEdit(prefs['ankiweb_user'])
        self.username.setPlaceholderText(_('Adresse e-mail du compte AnkiWeb'))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(_('Mot de passe (non conservé)'))
        self.password.returnPressed.connect(self.login)
        self.login_button, self.logout_button = QPushButton(_('Se connecter')), QPushButton(_('Se déconnecter'))
        self.login_button.clicked.connect(self.login)
        self.logout_button.clicked.connect(self.logout)
        credentials = QHBoxLayout()
        for widget, stretch in ((self.username, 2), (self.password, 2), (self.login_button, 0), (self.logout_button, 0)):
            credentials.addWidget(widget, stretch)
        account = QGroupBox(_('Compte AnkiWeb'))
        account_layout = QVBoxLayout(account)
        account_layout.addWidget(self.account_status)
        account_layout.addLayout(credentials)

        self.replace_older = QCheckBox(_('Remplacer les cartes déjà présentes avec un ancien type de note'))
        self.replace_older.setToolTip(_('Ces cartes, envoyées par une version précédente du plugin, n\'ont pas de son : '
                                        'elles sont supprimées puis recréées dans le deck choisi, et perdent leur '
                                        'historique de révision.'))

        notice = QLabel(_('Les cartes sont ajoutées à votre collection en ligne ; vos appareils les reçoivent à leur prochaine '
                          'synchronisation. Au premier usage, le plugin télécharge une fois les bibliothèques officielles Anki '
                          '(environ 12 Mo) dans son dossier de données ; rien d\'autre n\'est à installer.'))
        notice.setWordWrap(True)

        layout = QVBoxLayout(self)
        for widget in (self.summary, account, self.chooser, self.reverse, self.replace_older, notice):
            layout.addWidget(widget)
        layout.addLayout(self.buttons)

        self.update_state()
        if prefs['ankiweb_hkey']:
            self.run(lambda on_step: self.client.list_decks(self.account(), on_step), self.on_decks, N_('Connexion à AnkiWeb…'))

    def account(self):
        return {'hkey': prefs['ankiweb_hkey'], 'endpoint': prefs['ankiweb_endpoint']}

    def can_send(self):
        return bool(prefs['ankiweb_hkey'])

    def update_state(self):
        super().update_state()
        logged_in, idle = bool(prefs['ankiweb_hkey']), not self.busy()
        self.account_status.setText(_('Connecté en tant que {user}.').format(user=prefs['ankiweb_user']) if logged_in else _('Non connecté.'))
        for widget in (self.username, self.password, self.login_button):
            widget.setVisible(not logged_in)
            widget.setEnabled(idle)
        self.logout_button.setVisible(logged_in)
        self.logout_button.setEnabled(idle)

    def login(self):
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self.progress.setText(_('Saisissez l\'adresse e-mail et le mot de passe du compte AnkiWeb.'))
            return

        def task(on_step):
            if not self.client.is_installed():
                self.client.install(on_step)
            on_step(_('Connexion à AnkiWeb…'))
            login = self.client.login(username, password, prefs['ankiweb_endpoint'])
            account = {'hkey': login['hkey'], 'endpoint': login['endpoint']}
            return username, account, self.client.list_decks(account, on_step)

        self.run(task, self.on_logged_in, N_('Connexion à AnkiWeb…'))

    def on_logged_in(self, result):
        username, account, decks = result
        prefs['ankiweb_user'], prefs['ankiweb_hkey'] = username, account['hkey']
        self.password.clear()
        self.on_decks(decks)

    def on_decks(self, result):
        prefs['ankiweb_endpoint'] = result.get('endpoint') or prefs['ankiweb_endpoint']
        self.chooser.set_decks(result['decks'])
        self.progress.setText(_('{count} deck(s) dans la collection AnkiWeb.').format(count=len(result['decks'])))

    def logout(self):
        prefs['ankiweb_hkey'] = ''
        self.client.forget()
        self.chooser.set_decks([])
        self.progress.setText('')
        self.update_state()

    def send(self):
        deck, reverse, account = self.chooser.deck_name(), self.reverse.isChecked(), self.account()
        replace_older = self.replace_older.isChecked()
        self.remember(deck)
        self.run(
            lambda on_step: with_temporary_package(
                deck, self.notes, reverse, self.audio, on_step,
                lambda path, has_media: self.client.export(account, path, on_step, has_media, replace_older)),
            lambda result: self.on_sent(deck, result),
            N_('Préparation du paquet…'),
        )

    def on_sent(self, deck, result):
        self.on_decks(result)
        parts = [_('{count} nouvelle(s) note(s) ajoutée(s) au deck « {deck} » sur AnkiWeb.').format(count=result['added'], deck=deck)]
        if result['replaced']:
            parts.append(_('Dont {count} remplaçant une carte d\'un ancien type de note.').format(count=result['replaced']))
        if result['existing']:
            parts.append(_('{count} figuraient déjà dans la collection et restent dans leur deck.').format(count=result['existing']))
        if result['conflicting']:
            parts.append(_('{count} existent déjà avec un ancien type de note (deck « {decks} ») et n\'ont pas été envoyées : '
                           'cochez « Remplacer les cartes déjà présentes avec un ancien type de note » pour les remplacer.').format(
                count=result['conflicting'], decks=', '.join(result['conflicting_decks'])))
        if result['added']:
            parts.append(_('Synchronisez AnkiDroid pour les recevoir.'))
        self.progress.setText(' '.join(parts))

class ExportBar(QWidget):
    def __init__(self, collect_notes, reverse_allowed=True, audio_allowed=True):
        super().__init__()
        self.collect_notes, self.reverse_allowed, self.audio_allowed, self.worker = collect_notes, reverse_allowed, audio_allowed, None
        self.deck = QLineEdit(prefs['deck_name'])
        self.format = QComboBox()
        for key, label in EXPORT_FORMATS:
            self.format.addItem(_(label), key)
        self.format.setCurrentIndex(max(self.format.findData(prefs['export_format']), 0))
        self.reverse = QCheckBox(_('Cartes dans les deux sens'))
        self.reverse.setChecked(prefs['reverse'] and reverse_allowed)
        self.reverse.setVisible(reverse_allowed)
        self.reverse.setToolTip(_('Paquet .apkg uniquement : en CSV, le sens des cartes dépend du type de note choisi dans Anki.'))
        self.audio = QCheckBox(_('Prononciation'))
        self.audio.setChecked(prefs['audio'] and audio_allowed)
        self.audio.setVisible(audio_allowed)
        self.audio.setToolTip(_('Paquet .apkg, téléphone et AnkiWeb : enregistrement de Wiktionary quand il existe, '
                                'sinon voix de synthèse de l\'appareil qui affiche la carte.'))
        self.format.currentIndexChanged.connect(self.on_format_changed)
        self.on_format_changed()
        export = QPushButton(_('Exporter…'))
        export.clicked.connect(self.export)
        send = QPushButton(_('Envoyer au téléphone…'))
        send.setToolTip(_('Ouvre une fenêtre pour choisir le deck sur le téléphone et lancer l\'envoi par USB.'))
        send.clicked.connect(lambda: self.open_send_dialog(PhoneDialog))
        send_ankiweb = QPushButton(_('Envoyer vers AnkiWeb…'))
        send_ankiweb.setToolTip(_('Ouvre une fenêtre pour envoyer les cartes dans votre compte AnkiWeb, sans passer par le téléphone.'))
        send_ankiweb.clicked.connect(lambda: self.open_send_dialog(AnkiWebDialog))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        widgets = ((QLabel(_('Exporter dans un fichier : deck')), 0), (self.deck, 1), (self.format, 0), (self.reverse, 0),
                   (self.audio, 0), (export, 0), (send, 0), (send_ankiweb, 0))
        for widget, stretch in widgets:
            layout.addWidget(widget, stretch)

    def on_format_changed(self):
        self.reverse.setEnabled(self.format.currentData() == 'apkg')

    def export(self):
        (notes, skipped), deck, file_format = self.collect_notes(), self.deck.text().strip(), self.format.currentData()
        if not notes or not deck:
            error_dialog(self, _('Export Anki'),
                         _('Rien à exporter : il faut un nom de deck et au moins une ligne cochée exportable.'), show=True)
            return
        path = choose_save_file(self, f'kindle-vocab-anki-export-{file_format}', _('Exporter pour Anki'),
                                filters=[(self.format.currentText(), [file_format])],
                                initial_filename=f'{deck}.{file_format}')
        if not path:
            return
        if file_format == 'csv':
            try:
                apkg.write_csv(path, deck, notes)
            except OSError as error:
                error_dialog(self, _('Export Anki'), _('Écriture impossible : {error}').format(error=error), show=True)
                return
            self.on_exported(path, deck, file_format, len(notes), skipped)
            return

        progress = QProgressDialog(_('Préparation du paquet…'), '', 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        reverse, audio = self.reverse.isChecked(), self.audio.isChecked()
        self.worker = TaskWorker(lambda on_step: write_package(path, deck, notes, reverse, audio, on_step))
        self.worker.step.connect(progress.setLabelText)
        self.worker.done.connect(lambda _result, error: self.on_package_written(progress, error, path, deck, len(notes), skipped))
        self.worker.start()

    def on_package_written(self, progress, error, path, deck, count, skipped):
        progress.reset()
        if error:
            error_dialog(self, _('Export Anki'), _('Écriture impossible : {error}').format(error=error), show=True)
            return
        self.on_exported(path, deck, 'apkg', count, skipped)

    def on_exported(self, path, deck, file_format, count, skipped):
        prefs['deck_name'], prefs['export_format'] = deck, file_format
        self.remember_options()
        message = _('{count} note(s) exportée(s) dans {path}.').format(count=count, path=path)
        if skipped:
            message += '\n' + _('{count} ligne(s) cochée(s) sans contenu exportable ont été ignorée(s).').format(count=skipped)
        info_dialog(self, _('Export Anki'), message, show=True)

    def remember_options(self):
        if self.reverse_allowed:
            prefs['reverse'] = self.reverse.isChecked()
        if self.audio_allowed:
            prefs['audio'] = self.audio.isChecked()

    def open_send_dialog(self, dialog_class):
        notes, skipped = self.collect_notes()
        if not notes:
            error_dialog(self, _(dialog_class.title), _('Rien à envoyer : cochez au moins une ligne exportable.'), show=True)
            return
        if self.audio_allowed:
            prefs['audio'] = self.audio.isChecked()
        dialog_class(self, notes, skipped, self.reverse_allowed, self.audio.isChecked()).exec()

class TranslateWorker(QThread):
    progress = pyqtSignal(int, int)
    step = pyqtSignal(str)
    done = pyqtSignal(dict, str)

    def __init__(self, translator, groups, target, cache):
        super().__init__()
        self.translator, self.groups, self.target, self.cache = translator, groups, target, cache
        self.cancelled = False

    def run(self):
        result, error, offset = {}, '', 0
        total = sum(len(items) for _lang, items in self.groups)
        try:
            for lang, items in self.groups:
                self.prepare(lang)
                result.update(translators.translate_all(
                    self.translator, items, lang, self.target, self.cache,
                    lambda done, _total, offset=offset: self.progress.emit(offset + done, total),
                    lambda: self.cancelled,
                ))
                offset += len(items)
        except translators.TranslationError as exception:
            error = str(exception)
        except Exception as exception:
            error = _('Erreur inattendue : {error}').format(error=exception)
        self.done.emit(result, error)

    def prepare(self, lang):
        dictionary_path = getattr(self.translator, 'dictionary_path', None)
        if dictionary_path and not os.path.exists(dictionary_path(lang, self.target)):
            self.step.emit(_('Téléchargement du dictionnaire {source} → {target}…').format(
                source=language_label(translators.language_name(lang)), target=language_label(translators.language_name(self.target))))
            self.translator.download(lang, self.target)
        self.step.emit(_('Traduction en cours…'))


class ExtractWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(list, str)

    def __init__(self, llm, passages, target, cache, refresh):
        super().__init__()
        self.llm, self.passages, self.target, self.cache, self.refresh = llm, passages, target, cache, refresh
        self.cancelled = False

    def run(self):
        cards, error = [], ''
        try:
            cards = flashcards.extract_flashcards(
                self.llm, self.passages, self.target, translators.language_name(self.target), self.cache,
                self.progress.emit, lambda: self.cancelled, self.refresh,
            )
        except translators.TranslationError as exception:
            error = str(exception)
        except Exception as exception:
            error = _('Erreur inattendue : {error}').format(error=exception)
        self.done.emit(cards, error)


class CardsDialog(QDialog):
    def __init__(self, parent, cards):
        super().__init__(parent)
        self.cards = cards
        self.setWindowTitle(_('Flashcards extraites des surlignages'))
        self.resize(1100, 640)

        self.table = make_table(CARD_COLUMNS, CARD_SENTENCE)
        for column, width in ((CARD_FRONT, 220), (CARD_BACK, 220), (CARD_NOTE, 260)):
            self.table.setColumnWidth(column, width)
        self.table.setRowCount(len(cards))
        editable = READ_ONLY | Qt.ItemFlag.ItemIsEditable
        for row, card in enumerate(cards):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked)
            check.setData(KEY_ROLE, row)
            self.table.setItem(row, CARD_CHECK, check)
            self.table.setItem(row, CARD_KIND, make_cell(_(KIND_LABELS[card.kind])))
            self.table.setItem(row, CARD_FRONT, make_cell(card.front, editable))
            self.table.setItem(row, CARD_BACK, make_cell(card.back, editable))
            self.table.setItem(row, CARD_NOTE, make_cell(card.note, editable))
            self.table.setItem(row, CARD_SENTENCE, make_cell(card.sentence))
        self.table.resizeColumnToContents(CARD_CHECK)
        self.table.setSortingEnabled(True)

        vocabulary = sum(1 for card in cards if card.kind == 'vocabulary')
        summary = QLabel(_('{count} carte(s) : {vocabulary} de vocabulaire, {expressions} tournure(s). '
                           'Décochez celles à écarter ; recto, verso et remarque sont modifiables.').format(
            count=len(cards), vocabulary=vocabulary, expressions=len(cards) - vocabulary))

        self.export_bar = ExportBar(lambda: (self.notes(), 0))
        buttons = make_close_buttons()
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.export_bar)
        layout.addWidget(buttons)

    def notes(self):
        notes = []
        for row in range(self.table.rowCount()):
            check = self.table.item(row, CARD_CHECK)
            front, back = self.table.item(row, CARD_FRONT).text().strip(), self.table.item(row, CARD_BACK).text().strip()
            if check.checkState() != Qt.CheckState.Checked or not front or not back:
                continue
            card = self.cards[check.data(KEY_ROLE)]
            notes.append(apkg.Note(
                f'highlight:{front.lower()}', front, back, card.sentence, card.excerpt, card.book,
                ('kindle', 'surlignage', KIND_LABELS[card.kind].lower(), apkg.make_tag(card.book)),
                self.table.item(row, CARD_NOTE).text().strip(), lang=card.language,
            ))
        return notes


class VocabTab(QWidget):
    def __init__(self, path):
        super().__init__()
        self.conn, self.words, self.translations, self.filling, self.worker = None, {}, {}, False, None
        self.cache = make_cache()

        self.source = SourceRow('vocab.db', 'kindle-vocab-anki-db', (_('Base de vocabulaire Kindle'), ['db']), path)
        self.source.changed.connect(self.load)

        self.language, self.book, self.dates, self.search = QComboBox(), QComboBox(), DateRange(), QLineEdit()
        self.book.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.book.setMinimumContentsLength(30)
        self.search.setPlaceholderText(_('Rechercher un mot'))
        self.search.setClearButtonEnabled(True)
        self.language.currentIndexChanged.connect(self.on_language_changed)
        self.book.currentIndexChanged.connect(self.refresh)
        self.dates.changed.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)

        filters = QHBoxLayout()
        for widget, stretch in ((self.language, 0), (self.book, 1), (self.dates, 0), (self.search, 1)):
            filters.addWidget(widget, stretch)

        self.table = make_table(VOCAB_COLUMNS, COL_USAGE)
        self.table.setColumnWidth(COL_TRANSLATION, 240)
        self.table.setColumnWidth(COL_BOOK, 160)
        self.table.itemChanged.connect(self.on_item_changed)

        check_all, uncheck_all, self.count = QPushButton(_('Tout cocher')), QPushButton(_('Tout décocher')), QLabel('')
        check_all.clicked.connect(lambda: self.set_all_checked(True))
        uncheck_all.clicked.connect(lambda: self.set_all_checked(False))
        selection = QHBoxLayout()
        selection.addWidget(check_all)
        selection.addWidget(uncheck_all)
        selection.addWidget(self.count, 1)

        self.target, self.provider = QComboBox(), QComboBox()
        for name, code in sorted((language_label(name), code) for code, name in translators.LANGUAGES.items()):
            self.target.addItem(name, code)
        self.target.setCurrentIndex(max(self.target.findData(prefs['target_lang']), 0))
        for key, label in PROVIDERS:
            self.provider.addItem(_(label), key)
        self.provider.setCurrentIndex(max(self.provider.findData(prefs['provider']), 0))
        self.target.currentIndexChanged.connect(self.on_target_changed)
        self.provider.currentIndexChanged.connect(self.apply_cached_translations)
        self.replace = QCheckBox(_('Remplacer les traductions existantes'))
        translate = QPushButton(_('Traduire les mots cochés'))
        translate.clicked.connect(self.translate)

        translation = QHBoxLayout()
        for widget in (QLabel(_('Traduire vers')), self.target, QLabel(_('avec')), self.provider, self.replace):
            translation.addWidget(widget)
        translation.addStretch(1)
        translation.addWidget(translate)

        self.export_bar = ExportBar(self.collect_notes)

        layout = QVBoxLayout(self)
        layout.addWidget(self.source)
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        layout.addLayout(selection)
        layout.addLayout(translation)
        layout.addWidget(self.export_bar)

        if path:
            self.load(path)

    def load(self, path):
        try:
            with busy_cursor():
                conn = vocab.open_db(path)
                languages = vocab.list_languages(conn)
        except sqlite3.Error as error:
            error_dialog(self, _('Vocabulaire Kindle'), _('Impossible de lire {path} : {error}').format(path=path, error=error), show=True)
            return
        self.conn = conn
        prefs['vocab_db'] = path
        fill_combo(self.language, _('Toutes les langues'),
                   [(lang, f'{language_label(translators.language_name(lang))} ({count})') for lang, count in languages])
        self.on_language_changed()

    def on_language_changed(self):
        if self.conn is None:
            return
        books = vocab.list_books(self.conn, self.language.currentData())
        fill_combo(self.book, _('Tous les livres'), [(title, f'{title} ({count})') for title, count in books])
        self.refresh()

    def refresh(self):
        if self.conn is None:
            return
        start, end = self.dates.bounds()
        words = vocab.list_words(self.conn, vocab.Filters(self.language.currentData(), self.book.currentData(), start, end))
        needle = self.search.text().strip().lower()
        if needle:
            words = [word for word in words if needle in word.word.lower() or needle in word.stem.lower()]
        if words:
            self.dates.set_span(min(word.added for word in words).date(), max(word.added for word in words).date())

        self.words = {word.key: word for word in words}
        self.filling = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(words))
        for row, word in enumerate(words):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked)
            check.setData(KEY_ROLE, word.key)
            self.table.setItem(row, COL_CHECK, check)
            self.table.setItem(row, COL_WORD, make_cell(word.word))
            self.table.setItem(row, COL_STEM, make_cell(word.stem))
            self.table.setItem(row, COL_TRANSLATION, make_cell('', READ_ONLY | Qt.ItemFlag.ItemIsEditable))
            self.table.setItem(row, COL_DATE, make_cell(word.added.strftime('%Y-%m-%d')))
            self.table.setItem(row, COL_BOOK, make_cell(word.book))
            self.table.setItem(row, COL_USAGE, make_cell(word.usage))
        self.table.setSortingEnabled(True)
        self.table.resizeColumnToContents(COL_CHECK)
        self.filling = False
        self.apply_cached_translations()

    def on_target_changed(self):
        self.translations.clear()
        self.apply_cached_translations()

    def apply_cached_translations(self):
        translator = make_translator(self.provider.currentData())
        target = self.target.currentData()
        for lang in {word.lang for word in self.words.values()}:
            cached = self.cache.load(translator.cache_id, lang, target)
            for word in self.words.values():
                context = self.cache.context_key(word.usage) if translator.contextual else ''
                if word.lang == lang and (word.stem, context) in cached:
                    self.translations.setdefault(word.key, cached[(word.stem, context)])
        self.show_translations()

    def show_translations(self):
        self.filling = True
        for row in range(self.table.rowCount()):
            key = self.table.item(row, COL_CHECK).data(KEY_ROLE)
            self.table.item(row, COL_TRANSLATION).setText(self.translations.get(key, ''))
        self.filling = False
        self.update_count()

    def on_item_changed(self, item):
        if self.filling:
            return
        if item.column() == COL_TRANSLATION:
            key = self.table.item(item.row(), COL_CHECK).data(KEY_ROLE)
            self.translations[key] = item.text().strip()
        self.update_count()

    def set_all_checked(self, checked):
        self.filling = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, COL_CHECK).setCheckState(state)
        self.filling = False
        self.update_count()

    def checked_words(self):
        return [
            self.words[self.table.item(row, COL_CHECK).data(KEY_ROLE)]
            for row in range(self.table.rowCount())
            if self.table.item(row, COL_CHECK).checkState() == Qt.CheckState.Checked
        ]

    def update_count(self):
        checked = self.checked_words()
        translated = sum(1 for word in checked if self.translations.get(word.key))
        self.count.setText(_('{checked} mot(s) coché(s) sur {total}, dont {translated} traduit(s)').format(
            checked=len(checked), total=len(self.words), translated=translated))

    def translate(self):
        target, provider = self.target.currentData(), self.provider.currentData()
        words = [
            word for word in self.checked_words()
            if word.lang != target and (self.replace.isChecked() or not self.translations.get(word.key))
        ]
        if not words:
            info_dialog(self, _('Vocabulaire Kindle'), _('Aucun mot coché à traduire.'), show=True)
            return
        if provider in PAID_PROVIDERS and len(words) > CONFIRMATION_THRESHOLD and not question_dialog(
            self, _('Vocabulaire Kindle'),
            _('{count} mots vont être envoyés à {service}, un service payant. Continuer ?').format(
                count=len(words), service=self.provider.currentText()),
        ):
            return

        groups = {}
        for word in words:
            groups.setdefault(word.lang, []).append(translators.Item(word.key, word.word, word.stem, word.usage))

        progress = QProgressDialog(_('Traduction en cours…'), _('Annuler'), 0, len(words), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        self.worker = TranslateWorker(make_translator(provider), list(groups.items()), target, self.cache)
        self.worker.progress.connect(lambda done, _total: progress.setValue(done))
        self.worker.step.connect(progress.setLabelText)
        self.worker.done.connect(lambda result, error: self.on_translated(progress, result, error))
        progress.canceled.connect(lambda: setattr(self.worker, 'cancelled', True))
        self.worker.start()

    def on_translated(self, progress, result, error):
        progress.reset()
        self.translations.update(result)
        # Les lots réussis avant une erreur sont déjà en cache : on les récupère de là.
        self.apply_cached_translations()
        prefs['target_lang'], prefs['provider'] = self.target.currentData(), self.provider.currentData()
        if error:
            error_dialog(self, _('Vocabulaire Kindle'), error, show=True)

    def collect_notes(self):
        checked = self.checked_words()
        notes = [
            apkg.Note(word.key, word.stem, self.translations[word.key], word.usage, word.word, word.book,
                      ('kindle', word.lang, apkg.make_tag(word.book)), lang=word.lang)
            for word in checked if self.translations.get(word.key)
        ]
        return notes, len(checked) - len(notes)


class HighlightsTab(QWidget):
    def __init__(self, path):
        super().__init__()
        self.passages, self.visible, self.worker, self.cache, self.filling = [], [], None, make_cache(), False

        self.source = SourceRow('My Clippings.txt', 'kindle-vocab-anki-clippings', (_('Surlignages Kindle'), ['txt']), path)
        self.source.changed.connect(self.load)
        self.book, self.dates = QComboBox(), DateRange()
        self.book.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.book.setMinimumContentsLength(30)
        self.book.currentIndexChanged.connect(self.refresh)
        self.dates.changed.connect(self.refresh)
        filters = QHBoxLayout()
        filters.addWidget(self.book, 1)
        filters.addWidget(self.dates)

        self.table = make_table(HIGHLIGHT_COLUMNS, HIGHLIGHT_TEXT)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 190)
        self.table.setColumnWidth(5, 180)
        self.table.itemChanged.connect(lambda _item: self.update_count())

        check_all, uncheck_all, self.count = QPushButton(_('Tout cocher')), QPushButton(_('Tout décocher')), QLabel('')
        check_all.clicked.connect(lambda: self.set_all_checked(True))
        uncheck_all.clicked.connect(lambda: self.set_all_checked(False))
        copy, export = QPushButton(_('Copier en Markdown')), QPushButton(_('Exporter en Markdown…'))
        copy.clicked.connect(self.copy)
        export.clicked.connect(self.export)
        actions = QHBoxLayout()
        for widget, stretch in ((check_all, 0), (uncheck_all, 0), (self.count, 1), (copy, 0), (export, 0)):
            actions.addWidget(widget, stretch)

        self.export_bar = ExportBar(self.collect_notes, reverse_allowed=False, audio_allowed=False)

        self.target, self.provider = QComboBox(), QComboBox()
        for name, code in sorted((language_label(name), code) for code, name in translators.LANGUAGES.items()):
            self.target.addItem(name, code)
        self.target.setCurrentIndex(max(self.target.findData(prefs['target_lang']), 0))
        for key, label in LLM_PROVIDERS:
            self.provider.addItem(_(label), key)
        self.provider.setCurrentIndex(max(self.provider.findData(prefs['extract_provider']), 0))
        self.refresh_cards = QCheckBox(_('Réanalyser les passages déjà analysés'))
        extract = QPushButton(_('Extraire vocabulaire et tournures…'))
        extract.clicked.connect(self.extract)
        ai_row = QHBoxLayout()
        for widget in (QLabel(_('Flashcards par IA : ma langue')), self.target, QLabel(_('avec')), self.provider, self.refresh_cards):
            ai_row.addWidget(widget)
        ai_row.addStretch(1)
        ai_row.addWidget(extract)

        layout = QVBoxLayout(self)
        layout.addWidget(self.source)
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        layout.addWidget(self.export_bar)
        layout.addLayout(ai_row)

        if path:
            self.load(path)

    def load(self, path):
        try:
            with busy_cursor(), open(path, encoding='utf-8-sig') as file:
                self.passages = clippings.parse(file.read())
        except (OSError, UnicodeDecodeError) as error:
            error_dialog(self, _('Surlignages Kindle'), _('Impossible de lire {path} : {error}').format(path=path, error=error), show=True)
            return
        prefs['clippings'] = path
        fill_combo(self.book, _('Tous les livres'),
                   [(title, f'{title} ({count})') for title, count in clippings.list_books(self.passages)])
        self.refresh()

    def refresh(self):
        start, end = self.dates.bounds()
        self.visible = clippings.filter_passages(self.passages, self.book.currentData(), start, end)
        if self.visible:
            self.dates.set_span(min(p.date for p in self.visible).date(), max(p.date for p in self.visible).date())

        self.filling = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.visible))
        for row, passage in enumerate(self.visible):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked)
            check.setData(KEY_ROLE, row)
            self.table.setItem(row, HIGHLIGHT_CHECK, check)
            cells = (passage.date.strftime('%Y-%m-%d'), passage.book, passage.reference,
                     passage.text or '', ' / '.join(passage.notes))
            for column, text in enumerate(cells, start=1):
                self.table.setItem(row, column, make_cell(text))
        self.table.setSortingEnabled(True)
        self.table.resizeColumnToContents(HIGHLIGHT_CHECK)
        self.filling = False
        self.update_count()

    def set_all_checked(self, checked):
        self.filling = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, HIGHLIGHT_CHECK).setCheckState(state)
        self.filling = False
        self.update_count()

    def selected(self):
        checked = [
            self.table.item(row, HIGHLIGHT_CHECK).data(KEY_ROLE)
            for row in range(self.table.rowCount())
            if self.table.item(row, HIGHLIGHT_CHECK).checkState() == Qt.CheckState.Checked
        ]
        return [self.visible[index] for index in sorted(checked)]

    def update_count(self):
        if not self.filling:
            self.count.setText(_('{checked} passage(s) coché(s) sur {shown} affiché(s), {total} au total').format(
                checked=len(self.selected()), shown=len(self.visible), total=len(self.passages)))

    def collect_notes(self):
        selected = self.selected()
        notes = [
            apkg.Note(
                'passage:' + hashlib.sha1(passage.text.encode('utf-8')).hexdigest(), passage.text, passage.book,
                book=passage.book, tags=('kindle', 'surlignage', apkg.make_tag(passage.book)),
                note=' — '.join([*passage.notes, passage.reference]), passage=True,
            )
            for passage in selected if passage.text
        ]
        return notes, len(selected) - len(notes)

    def extract(self):
        passages = [passage for passage in self.selected() if passage.text]
        provider = self.provider.currentData()
        if not passages:
            error_dialog(self, _('Surlignages Kindle'), _('Aucun surlignage coché.'), show=True)
            return
        if provider in PAID_PROVIDERS and len(passages) > CONFIRMATION_THRESHOLD and not question_dialog(
            self, _('Surlignages Kindle'),
            _('{count} passages vont être envoyés à {service}, un service payant. Continuer ?').format(
                count=len(passages), service=self.provider.currentText()),
        ):
            return

        progress = QProgressDialog(_('Analyse des surlignages…'), _('Annuler'), 0, len(passages), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        self.worker = ExtractWorker(
            make_translator(provider), passages, self.target.currentData(), self.cache, self.refresh_cards.isChecked(),
        )
        def on_progress(done, total):
            progress.setValue(done)
            progress.setLabelText(_('Analyse des surlignages : {done}/{total} passage(s)…').format(done=done, total=total))

        self.worker.progress.connect(on_progress)
        self.worker.done.connect(lambda cards, error: self.on_extracted(progress, cards, error))
        progress.canceled.connect(lambda: setattr(self.worker, 'cancelled', True))
        self.worker.start()

    def on_extracted(self, progress, cards, error):
        progress.reset()
        prefs['target_lang'], prefs['extract_provider'] = self.target.currentData(), self.provider.currentData()
        if error:
            error_dialog(self, _('Surlignages Kindle'), error, show=True)
            return
        if not cards:
            info_dialog(self, _('Surlignages Kindle'), _('Le modèle n\'a rien trouvé à mettre en carte dans ces passages.'), show=True)
            return
        CardsDialog(self, cards).exec()

    def copy(self):
        selected = self.selected()
        QApplication.clipboard().setText(clippings.to_markdown(selected))
        self.count.setText(_('{count} passage(s) copié(s) dans le presse-papiers').format(count=len(selected)))

    def export(self):
        selected = self.selected()
        if not selected:
            error_dialog(self, _('Surlignages Kindle'), _('Aucun surlignage coché.'), show=True)
            return
        name = apkg.make_tag(self.book.currentData() or 'surlignages-kindle') or 'surlignages-kindle'
        path = choose_save_file(self, 'kindle-vocab-anki-markdown', _('Exporter les surlignages'),
                                filters=[('Markdown', ['md'])], initial_filename=f'{name}.md')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as file:
                file.write(clippings.to_markdown(selected))
        except OSError as error:
            error_dialog(self, _('Surlignages Kindle'), _('Écriture impossible : {error}').format(error=error), show=True)
            return
        info_dialog(self, _('Surlignages Kindle'), _('{count} passage(s) exporté(s) dans {path}.').format(count=len(selected), path=path), show=True)

class MainDialog(QDialog):
    def __init__(self, parent, vocab_db, clippings_path, plugin=None):
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle(_('Vocabulaire et surlignages Kindle'))
        self.resize(1150, 720)

        self.vocab_tab, self.highlights_tab = VocabTab(vocab_db), HighlightsTab(clippings_path)
        tabs = QTabWidget()
        tabs.addTab(self.vocab_tab, _('Vocabulaire'))
        tabs.addTab(self.highlights_tab, _('Surlignages'))

        buttons = make_close_buttons()
        buttons.rejected.connect(self.reject)
        if plugin is not None:
            preferences = buttons.addButton(_('Préférences…'), QDialogButtonBox.ButtonRole.ActionRole)
            preferences.clicked.connect(self.configure)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def configure(self):
        self.plugin.do_user_config(parent=self)
        self.vocab_tab.apply_cached_translations()
