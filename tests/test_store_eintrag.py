"""Store-Eintrag (NK-172): Längengrenzen des Partner Centers und der
Haftungshinweis im Wortlaut der App."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from nebenkostenfix import haftung
from nebenkostenfix.abrechnung_version import SOFTWARE_VERSION

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import store_neuerungen  # noqa: E402

EINTRAG = Path(__file__).resolve().parents[1] / 'packaging/windows/store/eintrag-de.md'
ZERTIFIZIERUNG = EINTRAG.with_name('zertifizierung-en.md')

# Grenzen laut Partner Center (Store listings), in Zeichen
GRENZEN = {
    'Beschreibung': 10000,
    'Kurzbeschreibung': 1000,
    'Neuerungen in dieser Version': 1500,
    'Copyright': 200,
    'Zusätzliche Lizenzbedingungen': 10000,
}


def _felder() -> dict[str, str]:
    teile = re.split(r'^## (.+)$', EINTRAG.read_text(encoding='utf-8'), flags=re.M)
    return {name.strip(): inhalt.strip() for name, inhalt in zip(teile[1::2], teile[2::2])}


def _liste(text: str) -> list[str]:
    return [zeile[2:].strip() for zeile in text.splitlines() if zeile.startswith('- ')]


@pytest.mark.parametrize('feld, grenze', GRENZEN.items())
def test_textfelder_passen(feld, grenze):
    text = _felder()[feld]
    assert 0 < len(text) <= grenze


def test_produktmerkmale():
    merkmale = _liste(_felder()['Produktmerkmale'])
    assert 1 <= len(merkmale) <= 20
    assert all(len(m) <= 200 for m in merkmale)


def test_suchbegriffe():
    begriffe = _liste(_felder()['Suchbegriffe'])
    assert 1 <= len(begriffe) <= 7
    assert all(len(b) <= 30 for b in begriffe)
    assert sum(len(b.split()) for b in begriffe) <= 21


def test_haftungshinweis_im_wortlaut_der_app():
    assert ' '.join(haftung.TEXT) in _felder()['Beschreibung']


def test_haftungshinweis_im_readme():
    """Derselbe Wortlaut steht auch im README (Abschnitt „## Haftung“)."""
    readme = (Path(__file__).resolve().parents[1] / 'README.md').read_text(encoding='utf-8')
    abschnitt = re.split(r'^## Haftung$', readme, flags=re.M, maxsplit=1)[1]
    abschnitt = abschnitt.split('\n## ', 1)[0]
    text = ' '.join(abschnitt.split())
    assert ' '.join(haftung.TEXT) in text


def test_gesiezt():
    text = ' '.join(_felder().values())
    assert not re.search(r'\b(du|dein|deine|dir|dich)\b', text, flags=re.I)


def test_pruefer_hinweise_widersprechen_sich_nicht():
    """Copilot zu #23: „there is no server“ neben dem lokalen Webserver auf
    127.0.0.1. Gemeint ist: kein entfernter Server, keiner des Herausgebers."""
    notiz = ZERTIFIZIERUNG.read_text(encoding='utf-8').split('\n---\n', 1)[1]
    assert '127.0.0.1' in notiz
    assert not re.search(r'\bno server\b', notiz, flags=re.I)


def test_neuerungen_gehoeren_zur_aktuellen_version():
    """Der Release setzt diesen Abschnitt im Store als Neuerungen (Job store,
    scripts/store_neuerungen.py). Ohne neuen Text stuenden dort die alten."""
    text = store_neuerungen.neuerungen(EINTRAG.read_text(encoding='utf-8'))
    assert text == _felder()['Neuerungen in dieser Version']
    assert SOFTWARE_VERSION in text
    assert 'Erste Fassung' not in text


def _einreichung():
    return {
        'Pricing': {'PriceId': 'Free'},
        'Listings': {
            'de-de': {'BaseListing': {'Description': 'Beschreibung', 'ReleaseNotes': 'alt'}},
            'en-us': {'BaseListing': {'Description': 'Description', 'ReleaseNotes': 'old'}},
        },
    }


def test_neuerungen_nur_im_deutschen_eintrag():
    einreichung = _einreichung()
    store_neuerungen.setzen(einreichung, 'neu')
    erwartet = _einreichung()
    erwartet['Listings']['de-de']['BaseListing']['ReleaseNotes'] = 'neu'
    assert einreichung == erwartet


def test_ohne_deutschen_eintrag_bricht_der_release_ab():
    einreichung = _einreichung()
    del einreichung['Listings']['de-de']
    with pytest.raises(SystemExit):
        store_neuerungen.setzen(einreichung, 'neu')


def _png(pfad: Path, breite: int, hoehe: int) -> Path:
    import struct
    import zlib
    kopf = struct.pack('>IIBBBBB', breite, hoehe, 8, 2, 0, 0, 0)
    pfad.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + kopf
                     + struct.pack('>I', zlib.crc32(b'IHDR' + kopf)))
    return pfad


def _groesse(pfad: Path) -> tuple[int, int]:
    import struct
    return struct.unpack('>II', pfad.read_bytes()[16:24])


def test_store_bilder_passen_zum_store():
    """Der Release lädt alle Bilder aus packaging/windows/store/bilder hoch;
    der Store nimmt höchstens zehn Screenshots."""
    bilder = sorted(store_neuerungen.BILDER.glob('*.png'))
    assert len(bilder) <= 10
    for bild in bilder:
        assert _groesse(bild) == (1920, 1080), bild.name


def test_neue_bilder_ersetzen_nur_deutsche_screenshots(tmp_path):
    einreichung = _einreichung()
    einreichung['Listings']['de-de']['BaseListing']['Images'] = [
        {'Id': '1', 'FileName': 'alt.png', 'FileStatus': 'Uploaded', 'ImageType': 'Screenshot'},
        {'Id': '2', 'FileName': 'logo.png', 'FileStatus': 'Uploaded', 'ImageType': 'StoreLogo300x300'},
    ]
    store_neuerungen.bilder_setzen(einreichung, [tmp_path / '1-heute.png', tmp_path / '2-rechnungen.png'])
    bilder = einreichung['Listings']['de-de']['BaseListing']['Images']
    assert [(b['FileName'], b['FileStatus']) for b in bilder] == [
        ('alt.png', 'PendingDelete'), ('logo.png', 'Uploaded'),
        ('1-heute.png', 'PendingUpload'), ('2-rechnungen.png', 'PendingUpload')]
    assert all(b['ImageType'] == 'Screenshot' for b in bilder[2:])
    assert 'Images' not in einreichung['Listings']['en-us']['BaseListing']


def test_zip_enthaelt_offenes_paket_und_bilder(tmp_path):
    """Das Zip ersetzt das von publish: ohne die MSIX fehlte der Einreichung das Paket."""
    import zipfile
    msix = tmp_path / 'msix'
    msix.mkdir()
    (msix / 'NebenkostenFix-1.0.0.msix').write_bytes(b'paket')
    bild = _png(tmp_path / '1-heute.png', 1920, 1080)
    einreichung = {'ApplicationPackages': [
        {'FileName': 'NebenkostenFix-0.9.0.msix', 'FileStatus': 'Uploaded'},
        {'FileName': 'NebenkostenFix-1.0.0.msix', 'FileStatus': 'PendingUpload'}]}
    ziel = tmp_path / 'paket.zip'
    store_neuerungen.packen(einreichung, [bild], msix, ziel)
    with zipfile.ZipFile(ziel) as archiv:
        assert sorted(archiv.namelist()) == ['1-heute.png', 'NebenkostenFix-1.0.0.msix']
        assert archiv.read('NebenkostenFix-1.0.0.msix') == b'paket'

    (msix / 'NebenkostenFix-1.0.0.msix').unlink()
    with pytest.raises(FileNotFoundError):
        store_neuerungen.packen(einreichung, [bild], msix, tmp_path / 'neu.zip')


def test_zip_ohne_offenes_paket_wird_nicht_gebaut(tmp_path):
    """Ein Zip nur mit Bildern ersetzte das von publish und damit das Paket."""
    bild = _png(tmp_path / '1-heute.png', 1920, 1080)
    ziel = tmp_path / 'paket.zip'
    for pakete in ([], [{'FileName': 'NebenkostenFix-0.9.0.msix', 'FileStatus': 'Uploaded'}]):
        with pytest.raises(FileNotFoundError):
            store_neuerungen.packen({'ApplicationPackages': pakete}, [bild], tmp_path, ziel)
        assert not ziel.exists()


def _ablauf(monkeypatch, tmp_path, einreichung, hochladen=None):
    """main() ohne Netz: msstore und Upload werden mitgeschrieben."""
    import json
    aufrufe = []

    def msstore(*argumente):
        if argumente[1] == 'get':
            return json.dumps(einreichung).encode()
        aufrufe.append(('update', json.loads(Path(argumente[-1]).read_text(encoding='utf-8'))))
        return b''

    monkeypatch.setattr(store_neuerungen, '_msstore', msstore)
    monkeypatch.setattr(store_neuerungen, 'hochladen', hochladen or (
        lambda adresse, datei: aufrufe.append(('hochladen', adresse, datei.exists()))))
    bilder = tmp_path / 'bilder'
    bilder.mkdir()
    _png(bilder / '1-heute.png', 1920, 1080)
    monkeypatch.setattr(store_neuerungen, 'BILDER', bilder)
    monkeypatch.setattr(store_neuerungen, 'MSIX', tmp_path / 'msix')
    store_neuerungen.main('produkt')
    return aufrufe


def test_release_laedt_bilder_nach_dem_update_hoch(monkeypatch, tmp_path):
    (tmp_path / 'msix').mkdir()
    (tmp_path / 'msix' / 'a.msix').write_bytes(b'paket')
    einreichung = _einreichung()
    einreichung['FileUploadUrl'] = 'https://blob.invalid/x?sig=y'
    einreichung['ApplicationPackages'] = [{'FileName': 'a.msix', 'FileStatus': 'PendingUpload'}]
    aufrufe = _ablauf(monkeypatch, tmp_path, einreichung)
    assert [a[0] for a in aufrufe] == ['update', 'hochladen']
    bilder = aufrufe[0][1]['Listings']['de-de']['BaseListing']['Images']
    assert [b['FileName'] for b in bilder] == ['1-heute.png']
    assert aufrufe[1][1:] == ('https://blob.invalid/x?sig=y', True)


def test_ohne_paket_bleiben_die_alten_bilder(monkeypatch, tmp_path):
    """Findet das Skript die MSIX nicht, setzt es nur die Neuerungen: ein Zip
    ohne Paket würde das hochgeladene Paket ersetzen."""
    einreichung = _einreichung()
    einreichung['FileUploadUrl'] = 'https://blob.invalid/x?sig=y'
    einreichung['ApplicationPackages'] = [{'FileName': 'a.msix', 'FileStatus': 'PendingUpload'}]
    aufrufe = _ablauf(monkeypatch, tmp_path, einreichung)
    assert [a[0] for a in aufrufe] == ['update']
    deutsch = aufrufe[0][1]['Listings']['de-de']['BaseListing']
    assert 'Images' not in deutsch
    assert deutsch['ReleaseNotes'] != 'alt'


def test_gescheiterter_upload_nimmt_die_bilder_zurueck(monkeypatch, tmp_path):
    """Nach dem Update stünden sonst Bilder auf PendingUpload, die nie ankommen,
    und die Einreichung scheiterte beim Commit."""
    (tmp_path / 'msix').mkdir()
    (tmp_path / 'msix' / 'a.msix').write_bytes(b'paket')
    einreichung = _einreichung()
    einreichung['FileUploadUrl'] = 'https://blob.invalid/x?sig=y'
    einreichung['ApplicationPackages'] = [{'FileName': 'a.msix', 'FileStatus': 'PendingUpload'}]

    def scheitern(adresse, datei):
        raise OSError('Verbindung abgebrochen')

    aufrufe = _ablauf(monkeypatch, tmp_path, einreichung, hochladen=scheitern)
    assert [a[0] for a in aufrufe] == ['update', 'update']
    assert aufrufe[0][1]['Listings']['de-de']['BaseListing']['Images']
    zurueck = aufrufe[1][1]['Listings']['de-de']['BaseListing']
    assert 'Images' not in zurueck
    assert zurueck['ReleaseNotes'] != 'alt'
