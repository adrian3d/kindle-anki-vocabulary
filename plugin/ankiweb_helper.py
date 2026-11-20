"""Exécuté dans un processus à part, avec les bibliothèques Anki téléchargées par le plugin en tête de sys.path."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import zipfile
from contextlib import closing


def N_(text):
    # Le processus d'AnkiWeb ne charge pas le plugin : ses messages sont traduits à l'arrivée, dans ankiweb.py.
    return text


def emit(**message):
    print(json.dumps(message, ensure_ascii=False), flush=True)


def main():
    request = json.loads(sys.stdin.read())
    if request.get('libraries'):
        sys.path.insert(0, request['libraries'])
    try:
        emit(ok=True, **ACTIONS[request['action']](request))
    except Exception as error:
        emit(ok=False, error=describe(error))


def login(request):
    from anki.collection import Collection

    col = Collection(scratch_collection(request))
    try:
        auth = col.sync_login(request['username'], request['password'], request.get('endpoint') or None)
    finally:
        col.close()
    return {'hkey': auth.hkey, 'endpoint': auth.endpoint or request.get('endpoint') or ''}


def list_decks(request):
    col, auth = open_synced(request)
    try:
        return {'decks': deck_names(col), 'endpoint': auth.endpoint}
    finally:
        col.close()


def export(request):
    from anki.collection import ImportAnkiPackageOptions, ImportAnkiPackageRequest

    col, auth = open_synced(request)
    try:
        emit(step=N_('Ajout des cartes…'))
        older = older_notes(col, request['package'])
        replaced = 0
        if request.get('replace_older') and older:
            # Convertir ces notes au nouveau type forcerait une synchronisation complète ; les supprimer, non.
            col.remove_notes(list(older))
            replaced, older = len(older), {}
        log = col.import_anki_package(
            ImportAnkiPackageRequest(package_path=request['package'], options=ImportAnkiPackageOptions())).log

        emit(step=N_('Envoi vers AnkiWeb…'))
        required = synchronize(col, auth)
        if required == 'FULL_UPLOAD':
            # Anki ne propose l'envoi complet d'office que lorsque le compte distant est vide.
            full_sync(col, auth, upload=True)
        elif required:
            raise RuntimeError(N_(
                'AnkiWeb demande une synchronisation complète, qui écraserait un côté. Rien n\'a été envoyé : '
                'synchronisez d\'abord vos appareils, puis réessayez.'
            ))
        if request.get('media'):
            emit(step=N_('Envoi des prononciations vers AnkiWeb…'))
            sync_media(col, auth)
        return {
            'added': len(log.new), 'existing': len(log.updated) + len(log.duplicate), 'replaced': replaced,
            'conflicting': len(log.conflicting), 'conflicting_decks': sorted(set(older.values())),
            'endpoint': auth.endpoint, 'decks': deck_names(col),
        }
    finally:
        col.close()


def older_notes(col, package):
    # Anki n'importe pas une note dont l'identifiant existe déjà avec un autre type de note : il la classe en conflit.
    guids, notetype = package_notes(package)
    if not guids:
        return {}
    marks = ','.join('?' * len(guids))
    rows = col.db.all(
        f'SELECT n.id, MIN(d.name) FROM notes n JOIN cards c ON c.nid = n.id JOIN decks d ON d.id = c.did '
        f'WHERE n.guid IN ({marks}) AND n.mid != ? GROUP BY n.id', *guids, notetype)
    return {note_id: deck for note_id, deck in rows}


def package_notes(package):
    with zipfile.ZipFile(package) as archive, tempfile.TemporaryDirectory() as directory:
        archive.extract('collection.anki2', directory)
        with closing(sqlite3.connect(os.path.join(directory, 'collection.anki2'))) as conn:
            rows = conn.execute('SELECT guid, mid FROM notes').fetchall()
    return [guid for guid, _mid in rows], (rows[0][1] if rows else 0)


def open_synced(request):
    from anki.collection import Collection
    from anki.sync_pb2 import SyncAuth

    os.makedirs(os.path.dirname(request['collection']), exist_ok=True)
    col = Collection(request['collection'])
    auth = SyncAuth(hkey=request['hkey'])
    if request.get('endpoint'):
        auth.endpoint = request['endpoint']
    try:
        emit(step=N_('Récupération de la collection AnkiWeb…'))
        if synchronize(col, auth):
            # La copie locale ne sert que de relais : en cas de divergence, c'est AnkiWeb qui fait foi.
            full_sync(col, auth, upload=False)
    except Exception:
        col.close()
        raise
    return col, auth


def synchronize(col, auth):
    from anki.sync_pb2 import SyncCollectionResponse

    output = col.sync_collection(auth, False)
    if output.new_endpoint:
        auth.endpoint = output.new_endpoint
    if output.required == SyncCollectionResponse.NO_CHANGES:
        return None
    return SyncCollectionResponse.ChangesRequired.Name(output.required)


def sync_media(col, auth):
    col.sync_media(auth)
    while True:
        status = col.media_sync_status()
        if not status.active:
            return
        time.sleep(0.5)


def full_sync(col, auth, upload):
    col.close_for_full_sync()
    col.full_upload_or_download(auth=auth, server_usn=None, upload=upload)
    col.reopen(after_full_sync=True)


def deck_names(col):
    return sorted((deck.name for deck in col.decks.all_names_and_ids()), key=str.lower)


def scratch_collection(request):
    path = request['collection'] + '.login'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def describe(error):
    text = str(error) or type(error).__name__
    kind = getattr(getattr(error, 'kind', None), 'name', '') or type(error).__name__
    if 'AUTH' in kind.upper() or 'auth' in text.lower():
        return N_('AnkiWeb a refusé les identifiants. Reconnectez-vous.')
    return text


ACTIONS = {'login': login, 'decks': list_decks, 'export': export}

if __name__ == '__main__':
    main()
