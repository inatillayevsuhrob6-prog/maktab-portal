/* Small, explicit replacements for formerly inline HTML event handlers. */
document.addEventListener('click', function (event) {
    const control = event.target.closest('[data-csp-action]');
    if (!control) return;

    const action = control.dataset.cspAction;
    if (action === 'scrollFeatures') {
        document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' });
        return;
    }
    if (action === 'historyBack') {
        if (window.history.length > 1) {
            event.preventDefault();
            window.history.back();
        }
        return;
    }
    if (action === 'toggleNews') {
        const card = control.closest('.news-card');
        if (!card) return;
        const expanded = card.classList.toggle('expanded');
        control.textContent = expanded ? '−' : '...';
        control.setAttribute('aria-label', expanded ? 'Matnni qisqartirish' : 'To‘liq matnni ko‘rsatish');
        return;
    }
    if (action === 'openJoinModal' && typeof window.openJoinModal === 'function') {
        window.openJoinModal(control, Number(control.dataset.clubId), control.dataset.clubName || '');
        return;
    }
    if (action === 'toggleClubMembers' && typeof window.toggleClubMembers === 'function') {
        window.toggleClubMembers(control, Number(control.dataset.clubId));
        return;
    }
    if (action === 'toggleNotifications' && typeof window[action] === 'function') {
        window[action](event);
        return;
    }
    if (typeof window[action] === 'function') window[action](event);
});

document.addEventListener('submit', function (event) {
    const form = event.target.closest('form[data-confirm]');
    if (form && !window.confirm(form.dataset.confirm)) event.preventDefault();
});

document.addEventListener('change', function (event) {
    const control = event.target;
    if (control.matches('[data-auto-submit]')) control.form?.requestSubmit();
    if (control.matches('[data-news-image-name]')) {
        const label = document.getElementById('news-image-name');
        if (label) label.textContent = control.files?.[0]?.name || 'JPG, PNG, GIF yoki WEBP (5 MB gacha)';
    }
});

document.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter') return;
    const control = event.target.closest('[data-enter-action]');
    if (control && typeof window[control.dataset.enterAction] === 'function') {
        event.preventDefault();
        window[control.dataset.enterAction]();
    }
});
