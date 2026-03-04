function crmApp() {
    return {
        // ==================== STATE ====================
        currentView: 'dashboard',
        searchQuery: '',
        searchResults: null,
        showSearchResults: false,

        // Dashboard
        dashboard: { loading: true, data: null },
        emailVolumeChart: null,

        // Contacts
        contacts: {
            loading: true,
            items: [],
            total: 0,
            page: 1,
            pageSize: 50,
            totalPages: 0,
            search: '',
            sortBy: 'email_count',
            sortDir: 'desc',
            filters: { is_vip: null, contact_type: '', tags: '', company_id: '' },
        },

        // Companies
        companies: {
            loading: true,
            items: [],
            total: 0,
            page: 1,
            pageSize: 50,
            totalPages: 0,
            search: '',
            sortBy: 'arr',
            sortDir: 'desc',
            filters: { company_type: '', account_tier: '' },
        },

        // Detail panel
        detail: {
            show: false,
            type: null,
            id: null,
            loading: true,
            data: null,
        },

        // Detail emails pagination
        emails: [],
        emailsPage: 1,
        emailsTotal: 0,
        emailsLoading: false,

        // Inline editing
        editing: { field: null, value: '' },
        newTag: '',

        // Debounce timers
        _notesTimer: null,

        // ==================== LIFECYCLE ====================
        init() {
            this.loadDashboard();
        },

        // ==================== NAVIGATION ====================
        navigate(view) {
            this.currentView = view;
            this.closeDetail();
            if (view === 'dashboard' && !this.dashboard.data) {
                this.loadDashboard();
            } else if (view === 'contacts' && this.contacts.items.length === 0) {
                this.loadContacts();
            } else if (view === 'companies' && this.companies.items.length === 0) {
                this.loadCompanies();
            }
        },

        // ==================== API HELPERS ====================
        async apiFetch(path, options = {}) {
            try {
                const headers = { 'Content-Type': 'application/json', ...options.headers };
                if (window.CRM_API_KEY) headers['X-API-Key'] = window.CRM_API_KEY;
                const resp = await fetch('/crm/api/' + path, {
                    headers,
                    ...options,
                });
                if (!resp.ok) throw new Error(`API error: ${resp.status}`);
                return await resp.json();
            } catch (err) {
                console.error('API error:', err);
                return null;
            }
        },

        // ==================== DASHBOARD ====================
        async loadDashboard() {
            this.dashboard.loading = true;
            const data = await this.apiFetch('dashboard');
            if (data) {
                this.dashboard.data = data;
                this.$nextTick(() => this.renderEmailChart());
            }
            this.dashboard.loading = false;
        },

        renderEmailChart() {
            const canvas = document.getElementById('emailVolumeChart');
            if (!canvas) return;

            if (this.emailVolumeChart) {
                this.emailVolumeChart.destroy();
            }

            const volumeData = [...(this.dashboard.data?.email_volume_by_month || [])].reverse();
            const labels = volumeData.map((d) => {
                const [y, m] = d.month.split('-');
                const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                return months[parseInt(m) - 1] + ' ' + y.slice(2);
            });
            const values = volumeData.map((d) => d.count);

            this.emailVolumeChart = new Chart(canvas, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Emails',
                        data: values,
                        backgroundColor: '#818CF8',
                        borderRadius: 4,
                        borderSkipped: false,
                        maxBarThickness: 40,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: '#1F2937',
                            titleFont: { size: 12 },
                            bodyFont: { size: 12 },
                            padding: 10,
                            cornerRadius: 8,
                            callbacks: {
                                label: (ctx) => ctx.parsed.y.toLocaleString() + ' emails',
                            },
                        },
                    },
                    scales: {
                        x: {
                            grid: { display: false },
                            ticks: { font: { size: 11 }, color: '#9CA3AF' },
                        },
                        y: {
                            grid: { color: '#F3F4F6' },
                            ticks: {
                                font: { size: 11 },
                                color: '#9CA3AF',
                                callback: (v) => v >= 1000 ? (v / 1000).toFixed(0) + 'K' : v,
                            },
                            beginAtZero: true,
                        },
                    },
                },
            });
        },

        // ==================== CONTACTS ====================
        async loadContacts() {
            this.contacts.loading = true;
            const params = new URLSearchParams({
                page: this.contacts.page,
                page_size: this.contacts.pageSize,
                sort_by: this.contacts.sortBy,
                sort_dir: this.contacts.sortDir,
            });
            if (this.contacts.search) params.set('search', this.contacts.search);
            if (this.contacts.filters.is_vip) params.set('is_vip', 'true');
            if (this.contacts.filters.contact_type) params.set('contact_type', this.contacts.filters.contact_type);
            if (this.contacts.filters.tags) params.set('tags', this.contacts.filters.tags);
            if (this.contacts.filters.company_id) params.set('company_id', this.contacts.filters.company_id);

            const data = await this.apiFetch('contacts?' + params.toString());
            if (data) {
                this.contacts.items = data.items || [];
                this.contacts.total = data.total || 0;
                this.contacts.totalPages = data.total_pages || 0;
            }
            this.contacts.loading = false;
        },

        // ==================== COMPANIES ====================
        async loadCompanies() {
            this.companies.loading = true;
            const params = new URLSearchParams({
                page: this.companies.page,
                page_size: this.companies.pageSize,
                sort_by: this.companies.sortBy,
                sort_dir: this.companies.sortDir,
            });
            if (this.companies.search) params.set('search', this.companies.search);
            if (this.companies.filters.company_type) params.set('company_type', this.companies.filters.company_type);
            if (this.companies.filters.account_tier) params.set('account_tier', this.companies.filters.account_tier);

            const data = await this.apiFetch('companies?' + params.toString());
            if (data) {
                this.companies.items = data.items || [];
                this.companies.total = data.total || 0;
                this.companies.totalPages = data.total_pages || 0;
            }
            this.companies.loading = false;
        },

        // ==================== DETAIL PANEL ====================
        async openContactDetail(id) {
            this.detail = { show: true, type: 'contact', id, loading: true, data: null };
            this.emails = [];
            this.emailsPage = 1;
            this.emailsTotal = 0;
            this.editing = { field: null, value: '' };
            this.newTag = '';

            const data = await this.apiFetch('contacts/' + id);
            if (data) {
                this.detail.data = data;
                this.detail.emails = data.recent_emails || [];
                this.detail.emailsTotal = data.email_stats?.total || 0;
                // Load paginated emails
                this.loadContactEmails(id, true);
            }
            this.detail.loading = false;
        },

        async openCompanyDetail(id) {
            this.detail = { show: true, type: 'company', id, loading: true, data: null };
            this.editing = { field: null, value: '' };

            const data = await this.apiFetch('companies/' + id);
            if (data) {
                this.detail.data = data;
            }
            this.detail.loading = false;
        },

        closeDetail() {
            this.detail.show = false;
            this.editing = { field: null, value: '' };
        },

        // ==================== CONTACT EMAILS ====================
        async loadContactEmails(id, reset = false) {
            if (reset) {
                this.emailsPage = 1;
                this.detail.emails = [];
            }
            this.detail.emailsLoading = true;
            const data = await this.apiFetch('contacts/' + id + '/emails?page=' + this.emailsPage + '&page_size=20');
            if (data) {
                if (reset) {
                    this.detail.emails = data.items || [];
                } else {
                    this.detail.emails = [...(this.detail.emails || []), ...(data.items || [])];
                }
                this.detail.emailsTotal = data.total || 0;
            }
            this.detail.emailsLoading = false;
        },

        async loadMoreEmails() {
            this.emailsPage++;
            await this.loadContactEmails(this.detail.id, false);
        },

        // ==================== INLINE EDITING ====================
        startEditing(field, value) {
            this.editing = { field, value };
            this.$nextTick(() => {
                const input = this.$el?.querySelector('input, select');
                if (input) input.focus();
            });
        },

        cancelEditing() {
            this.editing = { field: null, value: '' };
        },

        async saveField(field) {
            const value = this.editing.value;
            this.editing = { field: null, value: '' };

            if (this.detail.type === 'contact' && this.detail.id) {
                const body = {};
                body[field] = value || null;
                const result = await this.apiFetch('contacts/' + this.detail.id, {
                    method: 'PATCH',
                    body: JSON.stringify(body),
                });
                if (result && this.detail.data) {
                    this.detail.data.contact[field] = value;
                    // Update in list too
                    this.updateContactInList(this.detail.id, body);
                }
            }
        },

        // ==================== VIP TOGGLE ====================
        async toggleVip(contact) {
            const newVal = !contact.is_vip;
            contact.is_vip = newVal;
            await this.apiFetch('contacts/' + contact.id, {
                method: 'PATCH',
                body: JSON.stringify({ is_vip: newVal }),
            });
        },

        async toggleVipDetail() {
            if (!this.detail.data?.contact) return;
            const newVal = !this.detail.data.contact.is_vip;
            this.detail.data.contact.is_vip = newVal;
            await this.apiFetch('contacts/' + this.detail.id, {
                method: 'PATCH',
                body: JSON.stringify({ is_vip: newVal }),
            });
            this.updateContactInList(this.detail.id, { is_vip: newVal });
        },

        // ==================== TAGS ====================
        async addTag() {
            const tag = this.newTag.trim();
            if (!tag || !this.detail.data?.contact) return;
            const tags = [...(this.detail.data.contact.tags || []), tag];
            this.detail.data.contact.tags = tags;
            this.newTag = '';
            await this.apiFetch('contacts/' + this.detail.id, {
                method: 'PATCH',
                body: JSON.stringify({ tags }),
            });
        },

        async removeTag(idx) {
            if (!this.detail.data?.contact) return;
            const tags = [...(this.detail.data.contact.tags || [])];
            tags.splice(idx, 1);
            this.detail.data.contact.tags = tags;
            await this.apiFetch('contacts/' + this.detail.id, {
                method: 'PATCH',
                body: JSON.stringify({ tags }),
            });
        },

        // ==================== NOTES ====================
        async saveNotes(type) {
            if (type === 'contact' && this.detail.data?.contact) {
                await this.apiFetch('contacts/' + this.detail.id, {
                    method: 'PATCH',
                    body: JSON.stringify({ notes: this.detail.data.contact.notes || '' }),
                });
            } else if (type === 'company' && this.detail.data?.company) {
                await this.apiFetch('companies/' + this.detail.id, {
                    method: 'PATCH',
                    body: JSON.stringify({ notes: this.detail.data.company.notes || '' }),
                });
            }
        },

        // ==================== GLOBAL SEARCH ====================
        async globalSearch(q) {
            if (!q || q.length < 2) {
                this.searchResults = null;
                this.showSearchResults = false;
                return;
            }
            const data = await this.apiFetch('search?q=' + encodeURIComponent(q) + '&limit=10');
            if (data) {
                this.searchResults = data;
                this.showSearchResults = true;
            }
        },

        // ==================== SORTING ====================
        toggleSort(entity, field) {
            const state = this[entity];
            if (state.sortBy === field) {
                state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortBy = field;
                state.sortDir = 'desc';
            }
            state.page = 1;
            if (entity === 'contacts') this.loadContacts();
            else this.loadCompanies();
        },

        // ==================== LIST SYNC ====================
        updateContactInList(id, updates) {
            const idx = this.contacts.items.findIndex((c) => c.id === id);
            if (idx >= 0) {
                Object.assign(this.contacts.items[idx], updates);
            }
        },

        // ==================== BADGE HELPERS ====================
        contactTypeBadge(type) {
            const map = {
                'Champion': 'bg-green-100 text-green-800',
                'Decision Maker': 'bg-purple-100 text-purple-800',
                'Influencer': 'bg-blue-100 text-blue-800',
                'End User': 'bg-gray-100 text-gray-700',
                'Executive Sponsor': 'bg-indigo-100 text-indigo-800',
                'Blocker': 'bg-red-100 text-red-800',
            };
            return map[type] || 'bg-gray-100 text-gray-700';
        },

        companyTypeBadge(type) {
            const map = {
                'Customer': 'bg-green-100 text-green-800',
                'Prospect': 'bg-blue-100 text-blue-800',
                'Partner': 'bg-purple-100 text-purple-800',
                'Vendor': 'bg-orange-100 text-orange-800',
            };
            return map[type] || 'bg-gray-100 text-gray-700';
        },

        tierBadge(tier) {
            const map = {
                'Enterprise': 'bg-indigo-100 text-indigo-800',
                'Mid-Market': 'bg-blue-100 text-blue-800',
                'SMB': 'bg-gray-100 text-gray-700',
            };
            return map[tier] || 'bg-gray-100 text-gray-700';
        },

        // ==================== FORMAT HELPERS ====================
        formatNumber(n) {
            if (n == null) return '0';
            return Number(n).toLocaleString();
        },

        formatDate(d) {
            if (!d) return '-';
            const date = new Date(d);
            if (isNaN(date.getTime())) return '-';
            return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        },

        formatCurrency(n) {
            if (n == null) return '-';
            const num = Number(n);
            if (num >= 1000000) return '$' + (num / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
            if (num >= 1000) return '$' + (num / 1000).toFixed(0) + 'K';
            return '$' + num.toFixed(0);
        },

        timeAgo(d) {
            if (!d) return '';
            const now = new Date();
            const date = new Date(d);
            if (isNaN(date.getTime())) return '';
            const seconds = Math.floor((now - date) / 1000);

            if (seconds < 60) return 'just now';
            const minutes = Math.floor(seconds / 60);
            if (minutes < 60) return minutes + (minutes === 1 ? ' min ago' : ' mins ago');
            const hours = Math.floor(minutes / 60);
            if (hours < 24) return hours + (hours === 1 ? ' hour ago' : ' hours ago');
            const days = Math.floor(hours / 24);
            if (days < 30) return days + (days === 1 ? ' day ago' : ' days ago');
            const months = Math.floor(days / 30);
            if (months < 12) return months + (months === 1 ? ' month ago' : ' months ago');
            const years = Math.floor(months / 12);
            return years + (years === 1 ? ' year ago' : ' years ago');
        },

        isRenewalSoon(dateStr) {
            if (!dateStr) return false;
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) return false;
            const now = new Date();
            const diffDays = (date - now) / (1000 * 60 * 60 * 24);
            return diffDays >= 0 && diffDays <= 30;
        },
    };
}
