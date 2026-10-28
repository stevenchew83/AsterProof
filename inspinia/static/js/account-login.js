(() => {
    const toggle = document.querySelector('.auth-login-toggle');
    if (!toggle) return;

    const password = document.getElementById(toggle.getAttribute('aria-controls'));
    if (!password) return;

    toggle.hidden = false;
    toggle.addEventListener('click', () => {
        const isVisible = password.type === 'password';
        password.type = isVisible ? 'text' : 'password';
        toggle.setAttribute('aria-pressed', String(isVisible));
        toggle.setAttribute('aria-label', isVisible ? toggle.dataset.hideLabel : toggle.dataset.showLabel);
        toggle.querySelector('i').className = isVisible ? 'ti ti-eye-off' : 'ti ti-eye';
    });
})();
