"""Docker-Abbild im Release-Workflow: Tags je Version.

Befund: release.yml schob nur ``:<version>`` und ``:latest``. Wer bei einer
Reihe (z. B. 0.17) bleiben wollte, musste jedes Patch-Release von Hand in
``NK_VERSION`` nachziehen. Geprueft wird, dass der Workflow zusaetzlich
``:<major.minor>`` schiebt und diesen Wert aus der Versionsnummer bildet.
"""
from __future__ import annotations

from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WORKFLOW = WURZEL / '.github' / 'workflows' / 'release.yml'


def _workflow() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_der_version_job_bildet_die_reihe_aus_der_nummer():
    workflow = _workflow()
    assert 'echo "minor=${v%.*}" >> "$GITHUB_OUTPUT"' in workflow
    assert 'minor: ${{ steps.v.outputs.minor }}' in workflow


def test_das_abbild_bekommt_version_reihe_und_latest():
    workflow = _workflow()
    push = workflow[workflow.index('Bauen und nach GHCR schieben'):]
    tags = push[push.index('tags: |'):push.index('labels:')]

    for tag in ('${{ env.ABBILD }}:${{ env.VERSION }}',
                '${{ env.ABBILD }}:${{ env.MINOR }}',
                '${{ env.ABBILD }}:latest'):
        assert tag in tags, f'{tag} fehlt beim Push nach GHCR'
    assert 'MINOR: ${{ needs.version.outputs.minor }}' in workflow
