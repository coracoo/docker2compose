/**
 * D2C Web UI - Hand-drawn Sketch Style Edition
 * 处理前端交互逻辑和API调用
 */

// ==================== API 统一处理模块 ====================

const API = {
    baseUrl: '',
    defaultRetries: 3,
    defaultRetryDelay: 1000,

    /**
     * 统一 API 请求方法，带重试机制
     */
    async request(url, options = {}, retries = this.defaultRetries) {
        const fullUrl = url.startsWith('http') ? url : `${this.baseUrl}${url}`;
        
        try {
            const response = await fetch(fullUrl, {
                credentials: 'same-origin',  // 重要：携带 session cookie
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });

            // 检查 HTTP 错误
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            
            // 检查业务错误
            if (!result.success) {
                // 未授权，跳转到登录
                if (result.code === 'UNAUTHORIZED' || result.error?.includes('登录')) {
                    this.currentUser = null;
                    location.reload();
                    throw new Error('登录已过期，请重新登录');
                }
                throw new Error(result.error || '请求失败');
            }

            return result.data;
        } catch (error) {
            if (retries > 0 && this._isRetryableError(error)) {
                console.warn(`请求失败，${retries}次重试中...`, error.message);
                await this._delay(this.defaultRetryDelay);
                return this.request(url, options, retries - 1);
            }
            throw error;
        }
    },

    /**
     * GET 请求
     */
    get(url, retries) {
        return this.request(url, { method: 'GET' }, retries);
    },

    /**
     * POST 请求
     */
    post(url, data, retries) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data)
        }, retries);
    },

    /**
     * 判断是否可重试的错误
     */
    _isRetryableError(error) {
        const retryableErrors = [
            'Failed to fetch',
            'NetworkError',
            'network error',
            'timeout',
            '503',
            '502',
            '504'
        ];
        return retryableErrors.some(e => error.message.includes(e));
    },

    /**
     * 延迟函数
     */
    _delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
};

// ==================== 主要应用类 ====================

class D2CWebUI {
    constructor() {
        this.selectedContainers = new Set();
        this.containerGroups = [];
        this.currentYaml = '';
        this.autoRefreshInterval = null;
        this.isAutoRefreshActive = false;
        this.currentUser = null;
        this.containerSearchTerm = '';
        this.fileSearchTerm = '';
        this.originalFileData = null;
        
        // 防抖定时器
        this.containerSearchDebounceTimer = null;
        this.fileSearchDebounceTimer = null;
        
        this.init();
    }
    
    /**
     * 防抖函数
     * @param {Function} func - 要执行的函数
     * @param {number} wait - 等待时间（毫秒）
     * @returns {Function} - 防抖后的函数
     */
    debounce(func, wait = 300) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    /**
     * 通用模糊搜索方法
     * @param {string} text - 要搜索的文本
     * @param {string} searchTerm - 搜索关键词
     * @returns {boolean} - 是否匹配
     */
    fuzzyMatch(text, searchTerm) {
        if (!searchTerm || searchTerm.trim() === '') return true;
        if (!text) return false;
        
        const lowerText = text.toLowerCase();
        const lowerSearch = searchTerm.toLowerCase().trim();
        
        // 支持多关键词搜索（空格分隔）
        const keywords = lowerSearch.split(/\s+/).filter(k => k.length > 0);
        if (keywords.length === 0) return true;
        
        // 所有关键词都必须匹配
        return keywords.every(keyword => lowerText.includes(keyword));
    }
    
    /**
     * 高亮匹配文本
     * @param {string} text - 原始文本
     * @param {string} searchTerm - 搜索关键词
     * @returns {string} - 高亮后的HTML
     */
    highlightMatch(text, searchTerm) {
        if (!searchTerm || searchTerm.trim() === '' || !text) {
            return this.escapeHtml(text);
        }
        
        const keywords = searchTerm.toLowerCase().trim().split(/\s+/).filter(k => k.length > 0);
        if (keywords.length === 0) return this.escapeHtml(text);
        
        let highlighted = this.escapeHtml(text);
        keywords.forEach(keyword => {
            const regex = new RegExp(`(${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
            highlighted = highlighted.replace(regex, '<mark>$1</mark>');
        });
        
        return highlighted;
    }

    /**
     * 初始化应用
     */
    async init() {
        // 首先检查登录状态
        const isLoggedIn = await this.checkAuth();
        
        if (!isLoggedIn) {
            this.showLogin();
            return;
        }
        
        this.showApp();
        this.bindEvents();
        this.loadContainers();
        this.loadFileList();
        
        // 全局错误处理
        window.addEventListener('error', (event) => {
            console.error('全局错误:', event.error);
            this.showNotification('发生错误，请刷新页面重试', 'error');
        });

        window.addEventListener('unhandledrejection', (event) => {
            console.error('未处理的Promise:', event.reason);
            if (event.reason && event.reason.message && event.reason.message.includes('Failed to fetch')) {
                this.showNotification('网络连接失败，请检查网络', 'error');
            }
        });
    }

    // ==================== 认证相关 ====================
    
    async checkAuth() {
        try {
            const data = await API.get('/api/auth/me');
            this.currentUser = data;
            // 更新顶部用户名显示
            const usernameEl = document.getElementById('currentUsername');
            if (usernameEl && data.username) {
                usernameEl.textContent = data.username;
            }
            return true;
        } catch {
            return false;
        }
    }
    
    showLogin() {
        const overlay = document.getElementById('loginOverlay');
        const app = document.getElementById('appContainer');
        
        overlay.style.display = 'flex';
        app.style.display = 'none';
        
        // 绑定登录表单
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await this.login();
        });
    }
    
    showApp() {
        const overlay = document.getElementById('loginOverlay');
        const app = document.getElementById('appContainer');
        
        overlay.style.display = 'none';
        app.style.display = 'flex';
    }
    
    async login() {
        try {
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;
            
            // 确保包含凭证（cookies）
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',  // 重要：发送 cookies
                body: JSON.stringify({ username, password, remember: true })
            });
            
            const result = await response.json();
            
            if (!result.success) {
                throw new Error(result.error || '登录失败');
            }
            
            this.currentUser = result.data.user;
            // 更新顶部用户名显示
            const usernameEl = document.getElementById('currentUsername');
            if (usernameEl && result.data.user.username) {
                usernameEl.textContent = result.data.user.username;
            }
            this.showApp();
            this.bindEvents();
            this.loadContainers();
            this.loadFileList();
            
            // 检查是否需要修改密码
            if (result.data.require_password_change) {
                this.showNotification('首次登录，请修改默认密码', 'warning');
            }
        } catch (error) {
            this.showNotification(`登录失败: ${error.message}`, 'error');
        }
    }
    
    async logout() {
        try {
            await API.post('/api/auth/logout');
            this.currentUser = null;
            location.reload();
        } catch (error) {
            this.showNotification(`登出失败: ${error.message}`, 'error');
        }
    }
    
    openChangePassword() {
        const modal = new bootstrap.Modal(document.getElementById('changePasswordModal'));
        document.getElementById('changePasswordForm').reset();
        modal.show();
    }
    
    async savePassword() {
        const oldPassword = document.getElementById('oldPassword').value;
        const newPassword = document.getElementById('newPassword').value;
        const confirmPassword = document.getElementById('confirmPassword').value;
        
        if (!oldPassword || !newPassword || !confirmPassword) {
            this.showNotification('请填写所有密码字段', 'warning');
            return;
        }
        
        if (newPassword !== confirmPassword) {
            this.showNotification('两次输入的新密码不一致', 'warning');
            return;
        }
        
        if (newPassword.length < 6) {
            this.showNotification('新密码长度不能少于6位', 'warning');
            return;
        }
        
        try {
            await API.post('/api/auth/change-password', {
                old_password: oldPassword,
                new_password: newPassword
            });
            
            this.showNotification('密码修改成功', 'success');
            bootstrap.Modal.getInstance(document.getElementById('changePasswordModal')).hide();
        } catch (error) {
            this.showNotification(`修改失败: ${error.message}`, 'error');
        }
    }

    /**
     * 绑定事件监听器
     */
    bindEvents() {
        // 刷新按钮 - 全局刷新
        document.getElementById('refreshBtn')?.addEventListener('click', () => {
            this.refreshAll();
        });

        // 生成 Compose 按钮
        document.getElementById('generateComposeBtn')?.addEventListener('click', () => {
            this.generateCompose();
        });

        // 保存按钮
        document.getElementById('saveBtn')?.addEventListener('click', () => {
            this.saveCompose();
        });

        // 复制按钮
        document.getElementById('copyBtn')?.addEventListener('click', () => {
            this.copyToClipboard();
        });

        // 通知关闭按钮
        document.querySelector('.notification-close')?.addEventListener('click', () => {
            this.hideNotification();
        });

        // YAML 编辑器变化监听
        document.getElementById('yamlEditor')?.addEventListener('input', () => {
            this.updateSaveButtonState();
        });
        
        // 全部展开/收缩按钮
        document.getElementById('expandAllBtn')?.addEventListener('click', () => this.expandAllGroups());
        document.getElementById('collapseAllBtn')?.addEventListener('click', () => this.collapseAllGroups());
        
        // 容器列表搜索（带防抖）
        const containerSearchInput = document.getElementById('containerSearchInput');
        if (containerSearchInput) {
            const debouncedContainerSearch = this.debounce((value) => {
                this.containerSearchTerm = value;
                this.renderContainerGroups();
            }, 300);
            containerSearchInput.addEventListener('input', (e) => {
                debouncedContainerSearch(e.target.value);
            });
        }
        
        // 文件列表搜索（带防抖）
        const fileSearchInput = document.getElementById('fileSearchInput');
        if (fileSearchInput) {
            const debouncedFileSearch = this.debounce((value) => {
                this.fileSearchTerm = value;
                this.renderFileList(this.originalFileData);
            }, 300);
            fileSearchInput.addEventListener('input', (e) => {
                debouncedFileSearch(e.target.value);
            });
        }
        
        // 文件列表相关
        document.getElementById('refreshFilesBtn')?.addEventListener('click', () => this.loadFileList());
        
        // 生成全量 Compose 按钮
        document.getElementById('generateAllBtn')?.addEventListener('click', () => {
            this.generateAllCompose();
        });

        // 设置按钮
        document.getElementById('settingsBtn')?.addEventListener('click', () => {
            this.openSettings();
        });

        // 设置弹窗保存按钮
        document.getElementById('saveSettingsBtn')?.addEventListener('click', () => {
            this.saveSettings();
        });

        // CRON 选择器变化
        document.getElementById('cronInput')?.addEventListener('change', (e) => {
            const customInput = document.getElementById('customCronInput');
            if (e.target.value === 'custom') {
                customInput.style.display = 'block';
            } else {
                customInput.style.display = 'none';
            }
        });

        // 任务计划控制按钮
        document.getElementById('schedulerStatusBtn')?.addEventListener('click', () => {
            this.openSchedulerStatus();
        });
        
        document.getElementById('quickStartBtn')?.addEventListener('click', () => {
            this.startScheduler();
        });
        
        document.getElementById('quickStopBtn')?.addEventListener('click', () => {
            this.stopScheduler();
        });
        
        document.getElementById('quickRunOnceBtn')?.addEventListener('click', () => {
            this.runOnce();
        });
        
        // 日志操作按钮
        document.getElementById('refreshLogsBtn')?.addEventListener('click', () => {
            this.refreshLogs();
        });
        
        document.getElementById('clearLogsBtn')?.addEventListener('click', () => {
            this.clearLogs();
        });
        
        // 自动刷新切换按钮
        document.getElementById('autoRefreshToggle')?.addEventListener('click', () => {
            this.toggleAutoRefresh();
        });
        
        // 关于我按钮
        document.getElementById('aboutMeBtn')?.addEventListener('click', () => {
            this.openAboutMe();
        });
        
        // 用户菜单
        document.getElementById('changePasswordBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.openChangePassword();
        });
        
        document.getElementById('logoutBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            this.logout();
        });
        
        document.getElementById('savePasswordBtn')?.addEventListener('click', () => {
            this.savePassword();
        });
    }

    // ==================== 全局刷新 ====================
    
    async refreshAll() {
        // 全局刷新所有数据
        try {
            this.showLoading(true);
            
            // 并行加载所有数据
            await Promise.all([
                this.loadContainers(),
                this.loadFileList()
            ]);
            
            this.showNotification('刷新成功', 'success');
        } catch (error) {
            console.error('全局刷新失败:', error);
            this.showNotification('刷新失败', 'error');
        } finally {
            this.showLoading(false);
        }
    }

    // ==================== 容器相关 ====================

    async loadContainers() {
        try {
            this.showLoading(true);
            const data = await API.get('/api/containers');
            
            this.containerGroups = data;
            this.renderContainerGroups();
            this.showNotification('容器列表加载成功', 'success');
        } catch (error) {
            console.error('加载容器失败:', error);
            this.showNotification(`加载容器失败: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    renderContainerGroups() {
        const container = document.getElementById('containerGroups');
        const searchTerm = this.containerSearchTerm;
        
        if (this.containerGroups.length === 0) {
            container.innerHTML = `
                <div class="loading">
                    <i class="fas fa-exclamation-circle"></i>
                    <div>未找到运行中的容器</div>
                </div>
            `;
            return;
        }

        // 对每个分组内的容器按名称排序，并过滤
        const processedGroups = this.containerGroups
            .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()))
            .map(group => {
                const sortedContainers = [...group.containers].sort((a, b) => {
                    const nameA = a.name.toLowerCase();
                    const nameB = b.name.toLowerCase();
                    return nameA.localeCompare(nameB);
                });
                
                // 过滤容器
                const filteredContainers = searchTerm 
                    ? sortedContainers.filter(c => this.fuzzyMatch(c.name, searchTerm))
                    : sortedContainers;
                
                return {
                    ...group,
                    containers: sortedContainers,
                    filteredContainers: filteredContainers,
                    hasMatch: filteredContainers.length > 0 || this.fuzzyMatch(group.name, searchTerm)
                };
            }).filter(group => !searchTerm || group.hasMatch);

        if (processedGroups.length === 0) {
            container.innerHTML = `
                <div class="loading">
                    <i class="fas fa-search"></i>
                    <div>未找到匹配的容器</div>
                </div>
            `;
            return;
        }

        container.innerHTML = processedGroups.map((group, index) => {
            const displayContainers = searchTerm ? group.filteredContainers : group.containers;
            const runningCount = displayContainers.filter(c => c.status === 'running').length;
            const stoppedCount = displayContainers.length - runningCount;
            const groupStatus = runningCount > 0 ? 'running' : 'stopped';
            const statusIcon = groupStatus === 'running' ? 
                '<span class="group-status-icon running">R</span>' : 
                '<span class="group-status-icon stopped">S</span>';
            
            // 搜索时自动展开
            const isExpanded = searchTerm || index === 0;
            
            return `
            <div class="container-group">
                <div class="group-header ${isExpanded ? 'expanded' : ''}" onclick="app.toggleGroup('${this.escapeHtml(group.id)}')">
                    <div class="group-title">
                        ${statusIcon}
                        <span class="group-badge">${displayContainers.length}</span>
                        <i class="fas ${group.type === 'single' ? 'fa-cube' : 'fa-cubes'}"></i>
                        <span>${this.highlightMatch(this.escapeHtml(group.name), searchTerm)}</span>
                    </div>
                    <div class="group-actions">
                        <i class="fas fa-chevron-right group-toggle" style="${isExpanded ? 'transform: rotate(90deg);' : ''}"></i>
                    </div>
                </div>
                <div class="group-containers" style="display: ${isExpanded ? 'block' : 'none'}">
                    ${displayContainers.map((container, containerIndex) => {
                        const statusClass = container.status === 'running' ? 'running' : 'stopped';
                        const statusIcon = container.status === 'running' ? 
                            '<span class="container-status-badge running">R</span>' : 
                            '<span class="container-status-badge stopped">S</span>';
                        
                        return `
                        <div class="container-item ${index === 0 && containerIndex === 0 ? 'focused' : ''}" data-id="${this.escapeHtml(container.id)}" onclick="app.toggleContainer('${this.escapeHtml(container.id)}')">
                            <div class="container-checkbox ${this.selectedContainers.has(container.id) ? 'checked' : ''}"></div>
                            <div class="container-info">
                                <div class="container-name-row">
                                    <i class="fas fa-box container-icon" style="color: #3498db;"></i>
                                    <span class="container-name" title="${this.escapeHtml(container.name)}">${this.highlightMatch(this.escapeHtml(container.name), searchTerm)}</span>
                                    <span class="container-status ${container.status.toLowerCase()}">${container.status}</span>
                                </div>
                                <div class="container-details-row">
                                    <span title="${this.escapeHtml(container.image)}"><i class="fas fa-layer-group"></i> ${container.image.split('/').pop()?.substring(0, 15) || this.escapeHtml(container.image)}</span>
                                    <span title="${this.escapeHtml(container.network_mode)}"><i class="fas fa-network-wired"></i> ${this.escapeHtml(container.network_mode)}</span>
                                </div>
                            </div>
                        </div>
                        `;
                    }).join('')}
                </div>
            </div>
            `;
        }).join('');

        this.updateSelectionInfo();
    }

    toggleGroup(groupId) {
        const groupHeader = document.querySelector(`[onclick="app.toggleGroup('${groupId}')"]`);
        const groupContainers = groupHeader.nextElementSibling;
        const toggle = groupHeader.querySelector('.group-toggle');
        
        if (groupContainers.style.display === 'none') {
            groupContainers.style.display = 'block';
            groupHeader.classList.add('expanded');
            toggle.style.transform = 'rotate(90deg)';
        } else {
            groupContainers.style.display = 'none';
            groupHeader.classList.remove('expanded');
            toggle.style.transform = 'rotate(0deg)';
        }
    }

    toggleContainer(containerId) {
        if (this.selectedContainers.has(containerId)) {
            this.selectedContainers.delete(containerId);
        } else {
            this.selectedContainers.add(containerId);
        }

        this.updateContainerSelection();
        this.updateSelectionInfo();
        this.updateGenerateButtonState();
    }

    updateContainerSelection() {
        document.querySelectorAll('.container-item').forEach(item => {
            const containerId = item.getAttribute('data-id');
            const checkbox = item.querySelector('.container-checkbox');
            
            if (containerId && this.selectedContainers.has(containerId)) {
                item.classList.add('selected');
                checkbox.classList.add('checked');
            } else {
                item.classList.remove('selected');
                checkbox.classList.remove('checked');
            }
        });
    }

    updateSelectionInfo() {
        document.getElementById('selectedCount').textContent = this.selectedContainers.size;
    }

    updateGenerateButtonState() {
        const generateBtn = document.getElementById('generateComposeBtn');
        if (generateBtn) {
            generateBtn.disabled = this.selectedContainers.size === 0;
        }
    }

    updateSaveButtonState() {
        const saveBtn = document.getElementById('saveBtn');
        const yamlEditor = document.getElementById('yamlEditor');
        if (saveBtn && yamlEditor) {
            saveBtn.disabled = !yamlEditor.value.trim();
        }
    }

    expandAllGroups() {
        document.querySelectorAll('.group-header').forEach(header => {
            const groupContainers = header.nextElementSibling;
            const toggle = header.querySelector('.group-toggle');
            groupContainers.style.display = 'block';
            header.classList.add('expanded');
            toggle.style.transform = 'rotate(90deg)';
        });
    }

    collapseAllGroups() {
        document.querySelectorAll('.group-header').forEach(header => {
            const groupContainers = header.nextElementSibling;
            const toggle = header.querySelector('.group-toggle');
            groupContainers.style.display = 'none';
            header.classList.remove('expanded');
            toggle.style.transform = 'rotate(0deg)';
        });
    }

    // ==================== Compose 生成 ====================

    async generateCompose() {
        if (this.selectedContainers.size === 0) {
            this.showNotification('请先选择容器', 'warning');
            return;
        }

        try {
            this.showLoading(true);
            const data = await API.post('/api/compose', {
                container_ids: Array.from(this.selectedContainers)
            });

            this.currentYaml = data.yaml;
            this.showYamlEditor(this.currentYaml);
            this.showNotification('Compose 文件生成成功', 'success');
        } catch (error) {
            console.error('生成 Compose 失败:', error);
            this.showNotification(`生成失败: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    async generateAllCompose() {
        try {
            this.showLoading(true);
            const data = await API.post('/api/generate-all-compose');
            
            this.showNotification(`全量备份成功`, 'success');
            this.loadFileList();
        } catch (error) {
            console.error('生成全量 Compose 失败:', error);
            this.showNotification(`生成失败: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    showYamlEditor(content) {
        const placeholder = document.getElementById('editorPlaceholder');
        const editor = document.getElementById('yamlEditor');
        
        if (placeholder) placeholder.style.display = 'none';
        if (editor) {
            editor.style.display = 'block';
            editor.classList.add('active');
            editor.value = content;
        }
        
        this.updateSaveButtonState();
    }

    // ==================== 文件操作 ====================

    async loadFileList() {
        try {
            const data = await API.get('/api/files');
            this.originalFileData = data;
            this.renderFileList(data);
        } catch (error) {
            console.error('加载文件列表失败:', error);
            document.getElementById('fileList').innerHTML = `
                <div class="loading">
                    <i class="fas fa-exclamation-triangle"></i>
                    加载失败
                </div>
            `;
        }
    }

    renderFileList(data) {
        const fileList = document.getElementById('fileList');
        const searchTerm = this.fileSearchTerm;
        
        if (!data || (!data.root?.length && !(data.folders?.length > 0))) {
            fileList.innerHTML = '<div class="text-center text-muted p-3">暂无备份文件</div>';
            return;
        }

        let html = '';
        let hasMatch = false;
        
        // 渲染根目录文件（支持搜索过滤）
        if (data.root?.length > 0) {
            const filteredRoot = data.root.filter(file => this.fuzzyMatch(file.name, searchTerm));
            
            if (filteredRoot.length > 0 || !searchTerm) {
                hasMatch = true;
                const isExpanded = searchTerm ? 'expanded' : 'collapsed';
                const maxHeight = searchTerm ? 'max-height: none;' : 'max-height: 0;';
                const rotate = searchTerm ? 'transform: rotate(180deg);' : '';
                
                html += '<div class="folder-section">';
                html += '<div class="folder-header" onclick="app.toggleFolder(this)">';
                html += '<span><i class="fas fa-folder folder-icon"></i> 根目录</span>';
                html += `<i class="fas fa-chevron-down toggle-icon" style="${rotate}"></i>`;
                html += '</div>';
                html += `<div class="folder-content ${isExpanded}" style="${maxHeight}">`;
                
                filteredRoot.forEach(file => {
                    const modifiedDate = new Date(file.modified * 1000).toLocaleString('zh-CN');
                    const fileSize = this.formatFileSize(file.size);
                    const highlightedName = this.highlightMatch(file.name, searchTerm);
                    
                    html += `
                        <div class="file-item" onclick="app.loadFile('${this.escapeHtml(file.path)}', this)">
                            <i class="fas fa-file-code file-icon"></i>
                            <div class="file-info">
                                <div class="file-name">${highlightedName}</div>
                                <div class="file-date">${modifiedDate} · ${fileSize}</div>
                            </div>
                            <button class="btn btn-sm btn-danger delete-btn" onclick="event.stopPropagation(); app.deleteFile('${this.escapeHtml(file.path)}', event)">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    `;
                });
                
                html += '</div></div>';
            }
        }
        
        // 渲染文件夹（后端已按 modified 时间戳倒序排序，返回的是列表）
        const sortedFolders = data.folders || [];
        
        sortedFolders.forEach(folder => {
            // 过滤文件夹内的文件
            const filteredFiles = folder.files.filter(file => this.fuzzyMatch(file.name, searchTerm));
            const folderNameMatch = this.fuzzyMatch(folder.name, searchTerm);
            
            // 如果搜索词匹配文件夹名或内部有匹配的文件，则显示
            if (filteredFiles.length > 0 || folderNameMatch || !searchTerm) {
                hasMatch = true;
                const isExpanded = searchTerm ? true : false;
                const maxHeight = isExpanded ? 'max-height: none;' : 'max-height: 0;';
                const rotate = isExpanded ? 'transform: rotate(180deg);' : '';
                const filesToShow = searchTerm ? filteredFiles : folder.files;
                
                html += '<div class="folder-section">';
                html += '<div class="folder-header" onclick="app.toggleFolder(this)">';
                html += `<span><i class="fas fa-folder folder-icon"></i> ${this.highlightMatch(folder.name, searchTerm)}</span>`;
                html += '<div class="folder-actions">';
                html += `<button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); app.deleteFile('${this.escapeHtml(folder.path)}', event)" title="删除">`;
                html += '<i class="fas fa-trash"></i>';
                html += '</button>';
                html += `<i class="fas fa-chevron-down toggle-icon" style="${rotate}"></i>`;
                html += '</div>';
                html += '</div>';
                html += `<div class="folder-content ${isExpanded ? 'expanded' : 'collapsed'}" style="${maxHeight}">`;
                
                filesToShow.forEach(file => {
                    const modifiedDate = new Date(file.modified * 1000).toLocaleString('zh-CN');
                    const fileSize = this.formatFileSize(file.size);
                    const highlightedName = this.highlightMatch(file.name, searchTerm);
                    
                    html += `
                        <div class="file-item" onclick="app.loadFile('${this.escapeHtml(file.path)}', this)">
                            <i class="fas fa-file-code file-icon"></i>
                            <div class="file-info">
                                <div class="file-name">${highlightedName}</div>
                                <div class="file-date">${modifiedDate} · ${fileSize}</div>
                            </div>
                            <button class="btn btn-sm btn-danger delete-btn" onclick="event.stopPropagation(); app.deleteFile('${this.escapeHtml(file.path)}', event)">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    `;
                });
                
                html += '</div></div>';
            }
        });

        if (!hasMatch && searchTerm) {
            fileList.innerHTML = '<div class="text-center text-muted p-3">未找到匹配的文件</div>';
            return;
        }

        fileList.innerHTML = html;
    }

    toggleFolder(headerElement) {
        const content = headerElement.nextElementSibling;
        const toggleIcon = headerElement.querySelector('.toggle-icon');
        
        if (content.classList.contains('collapsed')) {
            content.classList.remove('collapsed');
            content.style.maxHeight = content.scrollHeight + 'px';
            toggleIcon.style.transform = 'rotate(180deg)';
        } else {
            content.classList.add('collapsed');
            content.style.maxHeight = '0';
            toggleIcon.style.transform = 'rotate(0deg)';
        }
    }

    async loadFile(filePath, targetElement = null) {
        try {
            // 更新 UI 状态
            document.querySelectorAll('.file-item').forEach(item => {
                item.classList.remove('selected');
            });
            
            if (targetElement) {
                targetElement.classList.add('selected');
            }
            
            const data = await API.post('/api/files/content', { path: filePath });
            
            this.showYamlEditor(data.content);
            document.getElementById('filenameInput').value = data.filename;
            this.showNotification('文件加载成功', 'success');
        } catch (error) {
            console.error('加载文件失败:', error);
            this.showNotification(`加载失败: ${error.message}`, 'error');
        }
    }

    async deleteFile(filePath, event) {
        event.stopPropagation();
        
        if (!confirm('确定要删除这个文件吗？')) {
            return;
        }
        
        try {
            this.showLoading(true);
            await API.post('/api/files/delete', { path: filePath });
            
            this.showNotification('删除成功', 'success');
            this.loadFileList();
        } catch (error) {
            console.error('删除文件失败:', error);
            this.showNotification(`删除失败: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    async saveCompose() {
        const filename = document.getElementById('filenameInput').value.trim();
        const content = document.getElementById('yamlEditor').value.trim();

        if (!filename) {
            this.showNotification('请输入文件名', 'warning');
            return;
        }

        if (!content) {
            this.showNotification('内容不能为空', 'warning');
            return;
        }

        try {
            this.showLoading(true);
            await API.post('/api/save-compose', { filename, content });
            
            this.showNotification('文件保存成功', 'success');
            // 保存后全局刷新
            await this.refreshAll();
        } catch (error) {
            console.error('保存文件失败:', error);
            this.showNotification(`保存失败: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    // ==================== 设置相关 ====================

    async openSettings() {
        try {
            const data = await API.get('/api/settings');
            
            // 网络配置复选框
            const networkInput = document.getElementById('networkInput');
            if (networkInput) {
                networkInput.checked = data.NETWORK === true || data.NETWORK === 'true';
            }
            // Healthcheck配置复选框
            const healthcheckInput = document.getElementById('healthcheckInput');
            if (healthcheckInput) {
                healthcheckInput.checked = data.SHOW_HEALTHCHECK === true || data.SHOW_HEALTHCHECK === 'true';
            }
            // CapAdd配置复选框
            const capAddInput = document.getElementById('capAddInput');
            if (capAddInput) {
                capAddInput.checked = data.SHOW_CAP_ADD === true || data.SHOW_CAP_ADD === 'true';
            }
            // Command配置复选框
            const commandInput = document.getElementById('commandInput');
            if (commandInput) {
                commandInput.checked = data.SHOW_COMMAND === true || data.SHOW_COMMAND === 'true';
            }
            // Entrypoint配置复选框
            const entrypointInput = document.getElementById('entrypointInput');
            if (entrypointInput) {
                entrypointInput.checked = data.SHOW_ENTRYPOINT === true || data.SHOW_ENTRYPOINT === 'true';
            }
            // 环境变量过滤关键词
            const envFilterInput = document.getElementById('envFilterInput');
            if (envFilterInput) {
                envFilterInput.value = data.ENV_FILTER_KEYWORDS || '';
            }
            document.getElementById('tzInput').value = data.TZ || 'Asia/Shanghai';
            
            // 设置 CRON 选择器
            const cronValue = data.CRON || '0 2 * * *';
            const cronSelect = document.getElementById('cronInput');
            const customInput = document.getElementById('customCronInput');
            const customValue = document.getElementById('customCronValue');
            
            // 检查是否是预设值
            const presetOptions = Array.from(cronSelect.options).map(o => o.value);
            if (presetOptions.includes(cronValue)) {
                cronSelect.value = cronValue;
                customInput.style.display = 'none';
            } else {
                cronSelect.value = 'custom';
                customInput.style.display = 'block';
                customValue.value = cronValue;
            }
            
            const modal = new bootstrap.Modal(document.getElementById('settingsModal'));
            modal.show();
        } catch (error) {
            console.error('加载设置失败:', error);
            this.showNotification(`加载设置失败: ${error.message}`, 'error');
        }
    }

    async saveSettings() {
        try {
            const cronSelect = document.getElementById('cronInput');
            let cronValue = cronSelect.value;
            
            // 如果是自定义，获取输入值
            if (cronValue === 'custom') {
                cronValue = document.getElementById('customCronValue').value.trim();
                if (!cronValue) {
                    this.showNotification('请输入自定义 CRON 表达式', 'warning');
                    return;
                }
            }
            
            const settings = {
                CRON: cronValue,
                NETWORK: String(document.getElementById('networkInput').checked),
                SHOW_HEALTHCHECK: String(document.getElementById('healthcheckInput').checked),
                SHOW_CAP_ADD: String(document.getElementById('capAddInput').checked),
                SHOW_COMMAND: String(document.getElementById('commandInput').checked),
                SHOW_ENTRYPOINT: String(document.getElementById('entrypointInput').checked),
                ENV_FILTER_KEYWORDS: document.getElementById('envFilterInput').value,
                TZ: document.getElementById('tzInput').value
            };
            
            const result = await API.post('/api/settings', { settings });
            
            if (result.reload_status) {
                this.showNotification('配置已保存并应用（调度器已热重载）', 'success');
            } else {
                this.showNotification('配置已保存', 'success');
            }
            bootstrap.Modal.getInstance(document.getElementById('settingsModal')).hide();
        } catch (error) {
            console.error('保存设置失败:', error);
            this.showNotification(`保存失败: ${error.message}`, 'error');
        }
    }

    // ==================== 定时任务相关 ====================

    openSchedulerStatus() {
        // 初始化自动刷新状态
        this.autoRefreshInterval = null;
        this.isAutoRefreshActive = false;
        
        const modalEl = document.getElementById('schedulerStatusModal');
        const modal = new bootstrap.Modal(modalEl);
        
        // 模态框关闭时停止自动刷新
        modalEl.addEventListener('hidden.bs.modal', () => {
            if (this.autoRefreshInterval) {
                clearInterval(this.autoRefreshInterval);
                this.autoRefreshInterval = null;
                this.isAutoRefreshActive = false;
            }
        }, { once: true });
        
        modal.show();
        
        this.refreshSchedulerStatus();
        this.refreshLogs();
    }

    async refreshSchedulerStatus() {
        // 未登录时不执行刷新
        if (!this.currentUser) {
            return;
        }
        try {
            // 获取当前设置
            const settings = await API.get('/api/settings');
            const currentCron = settings.CRON || 'manual';
            
            document.getElementById('schedulerCron').textContent = this.formatCronLabel(currentCron);
            
            // 获取任务状态
            const status = await API.get('/api/scheduler/status');
            
            const statusElement = document.getElementById('schedulerCurrentStatus');
            
            if (status.running) {
                statusElement.innerHTML = '<span class="status-indicator running">运行中</span>';
                statusElement.className = 'status-value running';
            } else {
                statusElement.innerHTML = '<span class="status-indicator stopped">已停止</span>';
                statusElement.className = 'status-value stopped';
            }
            
            // 更新下次执行时间
            if (status.next_run) {
                document.getElementById('schedulerNextRun').textContent = new Date(status.next_run).toLocaleString('zh-CN');
            } else {
                document.getElementById('schedulerNextRun').textContent = '-';
            }
            
            // 更新最后执行时间
            if (status.last_run) {
                document.getElementById('schedulerLastRun').textContent = new Date(status.last_run).toLocaleString('zh-CN');
            } else {
                document.getElementById('schedulerLastRun').textContent = '无记录';
            }
        } catch (error) {
            console.error('刷新任务状态失败:', error);
            document.getElementById('schedulerCurrentStatus').innerHTML = '<span class="status-indicator stopped">获取失败</span>';
        }
    }

    formatCronLabel(cron) {
        const labels = {
            'manual': '🔧 手动执行',
            'once': '▶️ 启动时一次',
            '*/10 * * * *': '⏰ 每 10 分钟',
            '*/30 * * * *': '⏰ 每 30 分钟',
            '0 * * * *': '⏰ 每小时',
            '0 */3 * * *': '⏰ 每 3 小时',
            '0 */6 * * *': '⏰ 每 6 小时',
            '0 2 * * *': '🌙 每天凌晨 2 点'
        };
        return labels[cron] || cron;
    }

    async startScheduler() {
        try {
            this.showLoading(true);
            await API.post('/api/scheduler/start');
            
            this.showNotification('定时任务启动成功', 'success');
            this.refreshSchedulerStatus();
        } catch (error) {
            console.error('启动定时任务失败:', error);
            this.showNotification(`启动失败: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    async stopScheduler() {
        try {
            this.showLoading(true);
            await API.post('/api/scheduler/stop');
            
            this.showNotification('定时任务停止成功', 'success');
            this.refreshSchedulerStatus();
        } catch (error) {
            console.error('停止定时任务失败:', error);
            this.showNotification(`停止失败: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    async runOnce() {
        try {
            this.showLoading(true);
            await API.post('/api/scheduler/run-once');
            
            this.showNotification('任务已启动，请稍后查看日志', 'success');
            setTimeout(() => this.refreshLogs(), 2000);
        } catch (error) {
            console.error('执行任务失败:', error);
            this.showNotification(`执行失败: ${error.message}`, 'error');
        } finally {
            this.showLoading(false);
        }
    }

    async refreshLogs() {
        // 未登录时不执行刷新
        if (!this.currentUser) {
            return;
        }
        try {
            const data = await API.get('/api/scheduler/logs');
            
            const logContainer = document.getElementById('logContainer');
            
            if (data.logs?.length > 0 && data.logs[0].source !== 'system') {
                const logContent = data.logs.map(log => {
                    const timestamp = new Date(log.timestamp).toLocaleString();
                    const level = log.level || 'info';
                    return `<div class="log-line ${level}"><span class="log-timestamp">${timestamp}</span>${this.escapeHtml(log.message)}</div>`;
                }).join('');
                
                logContainer.innerHTML = `<div class="log-content">${logContent}</div>`;
                logContainer.scrollTop = logContainer.scrollHeight;
            } else {
                logContainer.innerHTML = `
                    <div class="log-placeholder">
                        <i class="fas fa-file-alt"></i>
                        <p>暂无执行记录</p>
                        <small>执行任务后将显示日志</small>
                    </div>
                `;
            }
        } catch (error) {
            console.error('刷新日志失败:', error);
        }
    }

    async clearLogs() {
        if (!confirm('确定要清空所有执行日志吗？')) {
            return;
        }
        
        try {
            await API.post('/api/scheduler/clear-logs');
            this.showNotification('日志已清空', 'success');
            this.refreshLogs();
        } catch (error) {
            console.error('清空日志失败:', error);
            this.showNotification(`清空失败: ${error.message}`, 'error');
        }
    }

    toggleAutoRefresh() {
        const button = document.getElementById('autoRefreshToggle');
        
        if (this.isAutoRefreshActive) {
            if (this.autoRefreshInterval) {
                clearInterval(this.autoRefreshInterval);
                this.autoRefreshInterval = null;
            }
            this.isAutoRefreshActive = false;
            button.innerHTML = '<i class="fas fa-sync-alt"></i> 自动刷新';
            button.classList.remove('auto-refresh-active');
        } else {
            this.isAutoRefreshActive = true;
            button.innerHTML = '<i class="fas fa-sync-alt"></i> 停止刷新';
            button.classList.add('auto-refresh-active');
            
            this.autoRefreshInterval = setInterval(() => {
                this.refreshSchedulerStatus();
                this.refreshLogs();
            }, 3000);
        }
    }

    // ==================== 关于我 ====================

    openAboutMe() {
        const modal = new bootstrap.Modal(document.getElementById('aboutMeModal'));
        modal.show();
    }

    // ==================== 工具函数 ====================

    showNotification(message, type = 'info') {
        const notification = document.getElementById('notification');
        const messageElement = notification.querySelector('.notification-message');
        
        notification.classList.remove('success', 'error', 'info');
        notification.classList.add(type);
        
        messageElement.textContent = message;
        notification.classList.add('show');

        setTimeout(() => {
            this.hideNotification();
        }, type === 'error' ? 5000 : 3000);
    }

    hideNotification() {
        const notification = document.getElementById('notification');
        notification.classList.remove('show');
    }

    showLoading(show) {
        const overlay = document.getElementById('loadingOverlay');
        if (show) {
            overlay.classList.add('show');
        } else {
            overlay.classList.remove('show');
        }
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    escapeHtml(text) {
        if (!text) return '';
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    async copyToClipboard() {
        const content = document.getElementById('yamlEditor').value;
        
        if (!content.trim()) {
            this.showNotification('没有内容可复制', 'warning');
            return;
        }

        try {
            await navigator.clipboard.writeText(content);
            this.showNotification('已复制到剪贴板', 'success');
        } catch (error) {
            // 降级方案
            const textArea = document.createElement('textarea');
            textArea.value = content;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            this.showNotification('已复制到剪贴板', 'success');
        }
    }
}

// ==================== 初始化应用 ====================

let app;

document.addEventListener('DOMContentLoaded', () => {
    app = new D2CWebUI();
});
