// script.js

// ================================
// SIDE NAVIGATION
// ================================

function toggleSidenav() {
    const sidenav = document.getElementById('sidenav');
    const overlay = document.getElementById('sidenavOverlay');
    sidenav.classList.toggle('open');
    overlay.classList.toggle('active');
    document.body.style.overflow = sidenav.classList.contains('open') ? 'hidden' : '';
}

function collapseSidenav() {
    const sidenav = document.getElementById('sidenav');
    const main = document.querySelector('.dashboard-main');
    const icon = document.getElementById('collapseIcon');
    sidenav.classList.toggle('expanded');
    if (sidenav.classList.contains('expanded')) {
        if (icon) icon.classList.replace('fa-chevron-right', 'fa-chevron-left');
        if (main) main.style.marginLeft = '260px';
    } else {
        if (icon) icon.classList.replace('fa-chevron-left', 'fa-chevron-right');
        if (main) main.style.marginLeft = '64px';
    }
}

function expandIfCollapsed() {
    const sidenav = document.getElementById('sidenav');
    if (!sidenav.classList.contains('expanded')) collapseSidenav();
}

document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        const sidenav = document.getElementById('sidenav');
        if (sidenav && sidenav.classList.contains('open')) toggleSidenav();
    }
});

// ================================
// PAGE NAVIGATION
// ================================

const pageTitles = {
    'home': 'Home',
    'submit': 'Report Issue',
    'my-reports': 'My Reports',
    'community': 'Community Feed',
    'notifications': 'Notifications',
    'profile': 'Profile',
    'settings': 'Settings',
};

function showPage(pageId) {
    document.querySelectorAll('.page-content').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.sidenav-link').forEach(l => l.classList.remove('active'));

    const page = document.getElementById('page-' + pageId);
    if (page) page.classList.add('active');
    if (pageId === 'submit') {
        setTimeout(() => window.resizeGoogleReportMap?.('reportLocationMap'), 100);
    }

    const activeLink = document.querySelector(`.sidenav-link[data-page="${pageId}"]`);
    if (activeLink) activeLink.classList.add('active');

    const title = document.getElementById('pageTitle');
    if (title) title.textContent = pageTitles[pageId] || 'Home';

    const sidenav = document.getElementById('sidenav');
    if (sidenav && sidenav.classList.contains('open')) toggleSidenav();

    // Update URL without reload
    const url = new URL(window.location);
    url.searchParams.set('page', pageId);
    window.history.replaceState({}, '', url);

    // Fetch fresh fragment for My Reports to ensure it's always scoped to current user
    if (pageId === 'my-reports') {
        const reportsList = document.getElementById('myReportsList');
        if (reportsList) {
            fetch('/reports/my/fragment/', {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': (typeof getCookie === 'function') ? getCookie('csrftoken') : ''
                },
                credentials: 'same-origin'
            })
                .then(r => {
                    if (!r.ok) throw new Error('Failed to fetch my reports');
                    return r.text();
                })
                .then(html => {
                    reportsList.innerHTML = html;
                })
                .catch(err => {
                    console.error('Error loading my reports fragment:', err);
                });
        }
    }
}

document.addEventListener('DOMContentLoaded', function () {
    // Check URL param to auto-navigate to correct page
    const urlParams = new URLSearchParams(window.location.search);
    const page = urlParams.get('page');
    if (page) {
        showPage(page);
    }

    // Attach click events to sidenav links
    document.querySelectorAll('.sidenav-link[data-page]').forEach(link => {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            showPage(this.dataset.page);
        });
    });

    // Auto-dismiss success alerts after 4 seconds
    document.querySelectorAll('.alert-success').forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.5s ease';
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 500);
        }, 4000);
    });
});

// ================================
// FILE UPLOAD
// ================================

function updateFileName(input) {
    const fileName = document.getElementById('fileName');
    if (input.files && input.files[0]) {
        fileName.textContent = input.files[0].name;
        fileName.style.color = '#2563eb';
    }
}

// ================================
// NOTIFICATIONS
// ================================

function markAllRead() {
    fetch("/notifications/read/", {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'Content-Type': 'application/json',
        }
    }).then(() => {
        document.querySelectorAll('.notif-dot').forEach(d => d.remove());
        document.querySelectorAll('.notif-item.unread').forEach(i => i.classList.remove('unread'));
        document.querySelectorAll('.notif-badge, .sidenav-notif-badge').forEach(b => b.remove());
        const markBtn = document.querySelector('.notif-mark-read');
        if (markBtn) markBtn.remove();
    });
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        document.cookie.split(';').forEach(cookie => {
            cookie = cookie.trim();
            if (cookie.startsWith(name + '=')) {
                cookieValue = decodeURIComponent(cookie.slice(name.length + 1));
            }
        });
    }
    return cookieValue;
}



// ================================
// EDIT & DELETE MODALS
// ================================

function openEditModal(id, title, location, priority, description) {
    document.getElementById('editReportId').value = id;
    document.getElementById('editTitle').value = title;
    document.getElementById('editLocation').value = location;
    document.getElementById('editPriority').value = priority;
    document.getElementById('editDescription').value = description;
    document.getElementById('editModal').classList.add('open');
    document.body.style.overflow = 'hidden';
}

function closeEditModal() {
    document.getElementById('editModal').classList.remove('open');
    document.body.style.overflow = '';
}

function openDeleteModal(id, title) {
    document.getElementById('deleteReportId').value = id;
    document.getElementById('deleteReportTitle').textContent = '"' + title + '"';
    document.getElementById('deleteModal').classList.add('open');
    document.body.style.overflow = 'hidden';
}

function closeDeleteModal() {
    document.getElementById('deleteModal').classList.remove('open');
    document.body.style.overflow = '';
}

// Event delegation for edit/delete buttons using data attributes
document.addEventListener('click', function(e) {
    // Edit button
    const editBtn = e.target.closest('.btn-edit');
    if (editBtn) {
        openEditModal(
            editBtn.dataset.id,
            editBtn.dataset.title,
            editBtn.dataset.location,
            editBtn.dataset.priority,
            editBtn.dataset.description
        );
        return;
    }

    // Delete button
    const deleteBtn = e.target.closest('.btn-delete');
    if (deleteBtn) {
        openDeleteModal(deleteBtn.dataset.id, deleteBtn.dataset.title);
        return;
    }

    // Close modals on overlay click
    const editModal = document.getElementById('editModal');
    const deleteModal = document.getElementById('deleteModal');
    if (editModal && e.target === editModal) closeEditModal();
    if (deleteModal && e.target === deleteModal) closeDeleteModal();
});

// Close modals on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeEditModal();
        closeDeleteModal();
    }
});


// ================================
// PROOF LIGHTBOX PREVIEW
// ================================

function openProofPreview(url, title, address) {
    const overlay = document.getElementById('proofLightbox');
    const img = document.getElementById('proofLightboxImage');
    const caption = document.getElementById('proofLightboxCaption');
    const titleEl = document.getElementById('proofLightboxTitle');
    if (!overlay || !img) return;
    img.src = url;
    img.alt = (title || 'Proof') + ' image';
    caption.textContent = address || '';
    titleEl.textContent = title ? (title + ' — Proof') : 'Proof Preview';
    overlay.classList.add('active');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const closeBtn = document.getElementById('proofLightboxClose');
    if (closeBtn) closeBtn.focus();
}

function closeProofPreview() {
    const overlay = document.getElementById('proofLightbox');
    const img = document.getElementById('proofLightboxImage');
    if (!overlay) return;
    overlay.classList.remove('active');
    overlay.setAttribute('aria-hidden', 'true');
    if (img) {
        img.src = '';
        img.alt = '';
    }
    document.body.style.overflow = '';
}

// Delegate click for proof preview buttons
document.addEventListener('click', function (e) {
    const btn = e.target.closest('.open-proof-preview');
    if (btn) {
        const url = btn.dataset.proofUrl || btn.getAttribute('data-proof-url');
        const title = btn.dataset.proofTitle || btn.getAttribute('data-proof-title') || '';
        const address = btn.dataset.proofAddress || btn.getAttribute('data-proof-address') || '';
        if (url) {
            openProofPreview(url, title, address);
        }
        return;
    }

    // Close lightbox when clicking close button or overlay
    const closeBtn = e.target.closest('#proofLightboxClose');
    if (closeBtn) {
        closeProofPreview();
        return;
    }
    const lightboxOverlay = e.target.closest('#proofLightbox');
    if (lightboxOverlay && e.target === lightboxOverlay) {
        closeProofPreview();
        return;
    }
});

// Close on Escape key as well (accessible)
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        const overlay = document.getElementById('proofLightbox');
        if (overlay && overlay.classList.contains('active')) {
            closeProofPreview();
        }
    }
});

// Allow opening the image in a new tab when clicked
document.addEventListener('click', function (e) {
    const img = e.target.closest('#proofLightboxImage');
    if (img && img.src) {
        window.open(img.src, '_blank');
    }
});
