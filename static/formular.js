// Deutsche Hinweise der Formularprüfung. Der Browser -- und WebView2 in der
// Windows-App -- spricht sonst die Sprache des Systems ("This field is
// required."), auch wenn die Seite lang="de" trägt.
function formularHinweis(feld) {
    const v = feld.validity;
    if (v.valueMissing) {
        if (feld.type === 'checkbox') return 'Bitte setzen Sie das Häkchen.';
        if (feld.type === 'file') return 'Bitte wählen Sie eine Datei aus.';
        if (feld.tagName === 'SELECT' || feld.type === 'radio') return 'Bitte wählen Sie einen Eintrag aus.';
        return 'Bitte füllen Sie dieses Feld aus.';
    }
    if (v.tooShort) return `Bitte mindestens ${feld.minLength} Zeichen eingeben (bisher ${feld.value.length}).`;
    if (v.tooLong) return `Bitte höchstens ${feld.maxLength} Zeichen eingeben.`;
    if (v.badInput) return feld.type === 'number' ? 'Bitte geben Sie eine Zahl ein.' : 'Bitte geben Sie einen gültigen Wert ein.';
    if (v.typeMismatch) return feld.type === 'email' ? 'Bitte geben Sie eine gültige E-Mail-Adresse ein.' : 'Bitte geben Sie einen gültigen Wert ein.';
    if (v.rangeUnderflow) return `Der Wert muss mindestens ${feld.min} sein.`;
    if (v.rangeOverflow) return `Der Wert darf höchstens ${feld.max} sein.`;
    if (v.stepMismatch) return 'Bitte geben Sie einen gültigen Wert ein.';
    if (v.patternMismatch) return feld.title || 'Bitte halten Sie das verlangte Format ein.';
    return '';
}

function deutschPruefen(feld) {
    if (!feld.setCustomValidity) return;
    feld.setCustomValidity('');
    feld.setCustomValidity(formularHinweis(feld));
}

document.addEventListener('invalid', (e) => deutschPruefen(e.target), true);
// Jede Eingabe prüft neu. Nur leeren reicht nicht: Eine offene Hinweisblase
// liest beim Tippen die Meldung neu und zeigte dann den Systemtext
// ("Please lengthen this text ... using 2 characters").
['input', 'change'].forEach(art => document.addEventListener(art, (e) => deutschPruefen(e.target), true));

// Swoosh nach der Anmeldung: Indigo wischt über die Seite, dann
// geht das Formular ab. Der Zeitstempel sagt der App, dass sie die Fläche
// wieder wegziehen soll (index.html). Ohne Bewegungswunsch geht es sofort ab.
document.addEventListener('submit', (e) => {
    const form = e.target;
    if (e.defaultPrevented || !form.classList.contains('anmelde-karte')) return;
    try { sessionStorage.setItem('nk-einflug', String(Date.now())); } catch (err) { /* ohne Speicher kein Einflug */ }
    if (document.body.classList.contains('swoosh') || !form.requestSubmit
        || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    e.preventDefault();
    document.body.classList.add('swoosh');
    setTimeout(() => form.requestSubmit(e.submitter), 360);
});
// Zurück auf die Anmeldeseite (Seiten-Cache des Browsers): Fläche entfernen.
window.addEventListener('pageshow', () => document.body.classList.remove('swoosh'));
