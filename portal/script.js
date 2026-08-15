document.addEventListener('DOMContentLoaded', () => {
    const navItems = document.querySelectorAll('.nav-item');
    const iframe = document.getElementById('appFrame');
    const loadingOverlay = document.getElementById('loadingOverlay');

    // Handle navigation clicks
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Don't do anything if it's already active
            if (item.classList.contains('active')) return;

            // Update active states
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');

            // Show loader
            loadingOverlay.classList.remove('hidden');
            iframe.style.opacity = '0';

            // Change iframe source
            const targetUrl = item.getAttribute('data-target');
            iframe.src = targetUrl;
        });
    });

    // Hide loader when iframe finishes loading
    iframe.addEventListener('load', () => {
        loadingOverlay.classList.add('hidden');
        iframe.style.opacity = '1';
    });
});
