"""Neuerungen für den Microsoft Store (release.yml, Job store).

`msstore publish --noCommit` legt die Einreichung mit dem neuen Paket als
Entwurf an und übernimmt dabei den Eintrag der letzten Fassung, auch deren
„Neuerungen in dieser Version“. Dieses Skript setzt sie im deutschen Eintrag
aus packaging/windows/store/eintrag-de.md und ersetzt die Screenshots durch
packaging/windows/store/bilder/*.png (Rundgang --readme). Danach reicht der
Job ein.

Bilder und Paket gehen in einem Zip an FileUploadUrl. Das ersetzt das Zip, das
publish hochgeladen hat, deshalb liegt die MSIX (aus msix/) mit darin. Fehlen
Adresse oder MSIX, bleiben die alten Bilder und nur die Neuerungen wechseln.

    python scripts/store_neuerungen.py <produkt-id>

Das JSON läuft nur durch Python: pwsh würde Datumswerte und Umlaute beim
Durchreichen umschreiben, und `submission update` ersetzt die ganze
Einreichung.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
EINTRAG = WURZEL / 'packaging/windows/store/eintrag-de.md'
BILDER = WURZEL / 'packaging/windows/store/bilder'
MSIX = WURZEL / 'msix'


def neuerungen(eintrag: str) -> str:
    teile = re.split(r'^## (.+)$', eintrag, flags=re.M)
    felder = {name.strip(): inhalt.strip() for name, inhalt in zip(teile[1::2], teile[2::2])}
    return felder['Neuerungen in dieser Version']


def _deutsch(einreichung: dict) -> list[dict]:
    deutsch = [eintrag for sprache, eintrag in (einreichung.get('Listings') or {}).items()
               if sprache.lower().startswith('de')]
    if not deutsch:
        raise SystemExit('Die Einreichung hat keinen deutschen Eintrag.')
    return deutsch


def setzen(einreichung: dict, text: str) -> None:
    for eintrag in _deutsch(einreichung):
        eintrag['BaseListing']['ReleaseNotes'] = text


def bilder_setzen(einreichung: dict, bilder: list[Path]) -> None:
    """Alte Screenshots im deutschen Eintrag löschen, `bilder` hochladen."""
    for eintrag in _deutsch(einreichung):
        alt = eintrag['BaseListing'].get('Images') or []
        for bild in alt:
            if bild.get('ImageType') == 'Screenshot':
                bild['FileStatus'] = 'PendingDelete'
        eintrag['BaseListing']['Images'] = alt + [
            {'FileName': bild.name, 'FileStatus': 'PendingUpload', 'ImageType': 'Screenshot'}
            for bild in bilder]


def packen(einreichung: dict, bilder: list[Path], msix: Path, ziel: Path) -> None:
    """Zip für FileUploadUrl: noch offene Pakete und die Bilder."""
    pakete = [paket['FileName'] for paket in einreichung.get('ApplicationPackages') or []
              if paket.get('FileStatus') == 'PendingUpload']
    fehlt = [name for name in pakete if not (msix / Path(name).name).is_file()]
    if fehlt:
        raise FileNotFoundError(f'Paket nicht in {msix}: {", ".join(fehlt)}')
    with zipfile.ZipFile(ziel, 'w', zipfile.ZIP_DEFLATED) as archiv:
        for name in pakete:
            archiv.write(msix / Path(name).name, name)
        for bild in bilder:
            archiv.write(bild, bild.name)


def hochladen(adresse: str, datei: Path) -> None:
    # Die Adresse trägt eine Signatur, sie gehört in kein Log
    with datei.open('rb') as inhalt:
        anfrage = urllib.request.Request(adresse, data=inhalt, method='PUT', headers={
            'x-ms-blob-type': 'BlockBlob', 'x-ms-version': '2020-04-08',
            'Content-Length': str(datei.stat().st_size)})
        with urllib.request.urlopen(anfrage, timeout=900):
            pass


def _msstore(*argumente: str) -> bytes:
    # Fortschritt nach stderr, auf stdout steht nur das JSON
    return subprocess.run(['msstore', *argumente, '--output-stream', 'stderr'],
                          check=True, stdout=subprocess.PIPE).stdout


def main(produkt: str) -> None:
    einreichung = json.loads(_msstore('submission', 'get', produkt))
    setzen(einreichung, neuerungen(EINTRAG.read_text(encoding='utf-8')))
    bilder = sorted(BILDER.glob('*.png'))
    with tempfile.TemporaryDirectory() as ordner:
        archiv = Path(ordner) / 'paket.zip'
        if bilder and einreichung.get('FileUploadUrl'):
            try:
                packen(einreichung, bilder, MSIX, archiv)
                bilder_setzen(einreichung, bilder)
            except FileNotFoundError as fehler:
                print(f'Store-Bilder bleiben unverändert: {fehler}', file=sys.stderr)
                archiv.unlink(missing_ok=True)
        datei = Path(ordner) / 'einreichung.json'
        datei.write_text(json.dumps(einreichung), encoding='utf-8')
        _msstore('submission', 'update', produkt, '--payload', str(datei))
        if archiv.exists():
            hochladen(einreichung['FileUploadUrl'], archiv)


if __name__ == '__main__':
    main(sys.argv[1])
