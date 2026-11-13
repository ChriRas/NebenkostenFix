"""Die Datendateien der Abdeckung liegen im Arbeitsbaum, nicht fest in /tmp.

Befund: ``pyproject.toml`` schrieb die Datendatei von pytest-cov fest nach
``/tmp/nkfix-coverage``, das Ziel ``kern`` im Makefile nach
``/tmp/.coverage.kern``. Diese Pfade galten fuer jeden Arbeitsbaum (git
worktree) auf dem Rechner gleich. pytest-cov arbeitet im Parallelmodus: beim
Start loescht es die Datendatei samt allem, was ``<datei>.*`` heisst, am Ende
fuehrt es diese Dateien zusammen. Laufen zwei Arbeitsbaeume gleichzeitig,
loescht oder mischt der eine die Messung des anderen, und ``make schwelle``
oder ``make kern`` werden faelschlich rot, oder still gruen mit fremden
Werten.

Jetzt sind beide Pfade relativ, liegen also im Arbeitsbaum, in dem der Lauf
startet (im Container ``/app``). Die Kerndatei darf dabei nicht wie eine
Teildatei der Gesamtdatei heissen: ``.coverage.kern`` neben ``.coverage``
wuerde ``make test`` beim Start loeschen oder am Ende in die Gesamtzahl
mischen. Beide Dateien bleiben aus git und aus dem Abbild draussen.
``scripts/einzelschwelle.py`` liest die Datendatei relativ zur Projektwurzel,
damit es auch von einem anderen Arbeitsverzeichnis aus dieselbe Datei findet,
die pytest dort hinterlassen hat.
"""

import importlib.util
import re
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

WURZEL = Path(__file__).resolve().parent.parent


def _ist_absolut(pfad: str) -> bool:
    return PurePosixPath(pfad).is_absolute() or PureWindowsPath(pfad).is_absolute()


def _datendatei_der_suite() -> str:
    with (WURZEL / 'pyproject.toml').open('rb') as datei:
        inhalt = tomllib.load(datei)
    return inhalt['tool']['coverage']['run'].get('data_file', '.coverage')


def _datendateien_im_makefile() -> list[str]:
    text = (WURZEL / 'Makefile').read_text(encoding='utf-8')
    return re.findall(r'COVERAGE_FILE=(\S+)', text)


def _zeilen(name: str) -> set[str]:
    text = (WURZEL / name).read_text(encoding='utf-8')
    return {z.strip() for z in text.splitlines()
            if z.strip() and not z.strip().startswith('#')}


# --- Die Pfade -----------------------------------------------------------------

def test_datendatei_der_suite_liegt_im_arbeitsbaum():
    pfad = _datendatei_der_suite()
    assert not _ist_absolut(pfad), (
        f'data_file = "{pfad}" ist fuer alle Arbeitsbaeume dieselbe Datei; '
        'parallele Laeufe loeschen oder mischen sich gegenseitig die Messung.')


def test_kern_schreibt_seine_datendatei_in_den_arbeitsbaum():
    pfade = _datendateien_im_makefile()
    assert pfade, 'Das Ziel kern setzt keine eigene Datendatei mehr.'
    for pfad in pfade:
        assert not _ist_absolut(pfad), (
            f'COVERAGE_FILE={pfad} ist fuer alle Arbeitsbaeume dieselbe Datei.')


def test_kerndatei_ist_keine_teildatei_der_suite():
    """``<datei>.*`` loescht und mischt pytest-cov als Teil der Gesamtmessung.

    Hiesse die Kerndatei ``.coverage.kern`` neben ``.coverage``, nahme
    ``make test`` sie beim Start mit weg bzw. am Ende in die Gesamtzahl auf.
    """
    suite = _datendatei_der_suite()
    for pfad in _datendateien_im_makefile():
        assert pfad != suite, 'kern ueberschriebe die Datei, die schwelle liest.'
        assert not pfad.startswith(suite + '.'), (
            f'{pfad} sieht fuer pytest-cov aus wie eine Teildatei von {suite}.')


# --- Ausgeschlossen aus git und Abbild -----------------------------------------

@pytest.mark.parametrize('ignoredatei', ['.gitignore', '.dockerignore'])
def test_datendateien_sind_ausgeschlossen(ignoredatei):
    zeilen = _zeilen(ignoredatei)
    erwartet = {_datendatei_der_suite(), _datendatei_der_suite() + '.*'}
    for pfad in _datendateien_im_makefile():
        erwartet |= {pfad, pfad + '.*'}
    fehlt = sorted(erwartet - zeilen)
    assert not fehlt, f'{ignoredatei} schliesst {fehlt} nicht aus.'


# --- einzelschwelle liest die Datei der Projektwurzel --------------------------

def _einzelschwelle():
    pfad = WURZEL / 'scripts' / 'einzelschwelle.py'
    spec = importlib.util.spec_from_file_location('einzelschwelle_pfade', pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_einzelschwelle_liest_die_datendatei_der_projektwurzel(tmp_path, monkeypatch):
    """Ein relativer data_file meint die Projektwurzel, nicht das Arbeitsverzeichnis."""
    from coverage import CoverageData

    wurzel = tmp_path / 'baum'
    wurzel.mkdir()
    pyproject = wurzel / 'pyproject.toml'
    pyproject.write_text('[tool.coverage.run]\ndata_file = ".coverage"\n',
                         encoding='utf-8')
    modul = wurzel / 'modul.py'
    modul.write_text('a = 1\nb = 2\n', encoding='utf-8')
    daten = CoverageData(basename=str(wurzel / '.coverage'))
    daten.add_lines({str(modul): [1, 2]})
    daten.write()
    daten.close()

    anderswo = tmp_path / 'anderswo'
    anderswo.mkdir()
    monkeypatch.chdir(anderswo)
    monkeypatch.delenv('COVERAGE_FILE', raising=False)

    gemessen = _einzelschwelle().messen({'modul.py': 90.0}, pyproject=pyproject)
    assert gemessen == {'modul.py': 100.0}
