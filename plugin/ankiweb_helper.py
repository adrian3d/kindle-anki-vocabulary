"""Exécuté dans un processus à part, avec les bibliothèques Anki téléchargées par le plugin en tête de sys.path."""
import json
import os
import sys
import time


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
        before = col.note_count()
        emit(step='Ajout des cartes…')
        col.import_anki_package(ImportAnkiPackageRequest(package_path=request['package'], options=ImportAnkiPackageOptions()))
        added = col.note_count() - before

        emit(step='Envoi vers AnkiWeb…')
        required = synchronize(col, auth)
        if required == 'FULL_UPLOAD':
            # Anki ne propose l'envoi complet d'office que lorsque le compte distant est vide.
            full_sync(col, auth, upload=True)
        elif required:
            raise RuntimeError(
                'AnkiWeb demande une synchronisation complète, qui écraserait un côté. Rien n\'a été envoyé : '
                'synchronisez d\'abord vos appareils, puis réessayez.'
            )
        if request.get('media'):
            emit(step='Envoi des prononciations vers AnkiWeb…')
            sync_media(col, auth)
        return {'added': added, 'updated_or_existing': len(request.get('guids', [])) - added, 'endpoint': auth.endpoint,
                'decks': deck_names(col)}
    finally:
        col.close()


def open_synced(request):
    from anki.collection import Collection
    from anki.sync_pb2 import SyncAuth

    os.makedirs(os.path.dirname(request['collection']), exist_ok=True)
    col = Collection(request['collection'])
    auth = SyncAuth(hkey=request['hkey'])
    if request.get('endpoint'):
        auth.endpoint = request['endpoint']
    try:
        emit(step='Récupération de la collection AnkiWeb…')
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
        if status.progress.checked:
            emit(step=f'Envoi des prononciations vers AnkiWeb : {status.progress.checked}')
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
        return 'AnkiWeb a refusé les identifiants. Reconnectez-vous.'
    return text


ACTIONS = {'login': login, 'decks': list_decks, 'export': export}

if __name__ == '__main__':
    main()
