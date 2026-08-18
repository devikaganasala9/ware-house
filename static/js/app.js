document.addEventListener('DOMContentLoaded', () => {
    // 1. Initialize Lucide Icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }

    // 2. Dark/Light Theme Switcher
    const themeToggleBtn = document.getElementById('theme-toggle');
    if (themeToggleBtn) {
        // Check saved preference or default to light
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
        updateThemeIcon(savedTheme);

        themeToggleBtn.addEventListener('click', () => {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            updateThemeIcon(newTheme);
            showToast(`Theme switched to ${newTheme} mode.`, 'info');
        });
    }

    function updateThemeIcon(theme) {
        const iconElement = themeToggleBtn.querySelector('i');
        if (iconElement) {
            if (theme === 'dark') {
                iconElement.setAttribute('data-lucide', 'sun');
                iconElement.className = 'lucide lucide-sun';
            } else {
                iconElement.setAttribute('data-lucide', 'moon');
                iconElement.className = 'lucide lucide-moon';
            }
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
    }

    // 3. Modal Opening & Closing Listeners
    window.openModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.style.display = 'flex';
        }
    }

    window.closeModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.style.display = 'none';
        }
    }

    // Close modal on background click
    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-overlay')) {
            e.target.style.display = 'none';
        }
    });

    // 4. Global Toast System
    window.showToast = function(message, type = 'success') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        let iconName = 'check-circle';
        if (type === 'warning') iconName = 'alert-triangle';
        if (type === 'error') iconName = 'x-circle';
        if (type === 'info') iconName = 'info';

        toast.innerHTML = `
            <i data-lucide="${iconName}"></i>
            <span>${message}</span>
        `;
        
        container.appendChild(toast);
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }

        // Remove toast after 4 seconds
        setTimeout(() => {
            toast.style.animation = 'slideIn 0.3s ease reverse forwards';
            setTimeout(() => {
                toast.remove();
            }, 300);
        }, 4000);
    }
});

// Helper for AJAX posts
async function postData(url = '', data = {}) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams(data)
    });
    return response.json();
}
