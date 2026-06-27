const {
    ItemView,
    Notice,
    Plugin,
    PluginSettingTab,
    Setting,
    setIcon,
} = require("obsidian");
const childProcess = require("child_process");
const path = require("path");

const VIEW_TYPE = "zhiwei-kb-evidence-view";

const DEFAULT_SETTINGS = {
    apiBase: "http://localhost:8765",
    pythonCommand: "python",
    autoOpen: true,
    autoStartBackend: false,
    maxResults: 10,
};

class ZhiweiEvidencePlugin extends Plugin {
    async onload() {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
        this.serverProcess = null;

        this.registerView(VIEW_TYPE, (leaf) => new ZhiweiEvidenceView(leaf, this));
        this.addRibbonIcon("book-open-check", "打开知微规范证据台", () => this.activateView());
        this.addCommand({
            id: "open-zhiwei-evidence",
            name: "打开知微规范证据台",
            callback: () => this.activateView(),
        });
        this.addCommand({
            id: "search-selection-in-zhiwei-kb",
            name: "用知微 KB 搜索选中文本",
            editorCallback: (editor) => {
                const query = editor.getSelection() || editor.getLine(editor.getCursor().line);
                this.activateView(query.trim());
            },
        });
        this.addSettingTab(new ZhiweiSettingTab(this.app, this));

        if (this.settings.autoOpen) {
            this.app.workspace.onLayoutReady(() => this.activateView());
        }
        if (this.settings.autoStartBackend) {
            this.app.workspace.onLayoutReady(() => this.startServer({ silent: true }));
        }
    }

    onunload() {
        this.app.workspace.detachLeavesOfType(VIEW_TYPE);
        this.stopServer({ silent: true });
    }

    async saveSettings() {
        await this.saveData(this.settings);
    }

    async activateView(initialQuery) {
        const { workspace } = this.app;
        let leaf = workspace.getLeavesOfType(VIEW_TYPE)[0];
        if (!leaf) {
            leaf = workspace.getRightLeaf(false) || workspace.getLeaf(true);
            await leaf.setViewState({ type: VIEW_TYPE, active: true });
        }
        await workspace.revealLeaf(leaf);
        const view = leaf.view;
        if (initialQuery && view instanceof ZhiweiEvidenceView) {
            view.setQuery(initialQuery);
        }
    }

    endpoint(pathname) {
        return this.settings.apiBase.replace(/\/$/, "") + pathname;
    }

    async fetchJson(pathname, options = {}, timeoutMs = 10000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(this.endpoint(pathname), Object.assign({}, options, { signal: controller.signal }));
            if (!response.ok) {
                throw new Error(`${response.status} ${response.statusText}`.trim());
            }
            return await response.json();
        } finally {
            clearTimeout(timer);
        }
    }

    checkBackend() {
        return this.fetchJson("/api/status", {}, 2500).then(() => true).catch(() => false);
    }

    searchApi(query, maxResults) {
        return this.fetchJson("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query, max_results: maxResults || this.settings.maxResults }),
        }, 12000);
    }

    suggestApi(query) {
        return this.fetchJson("/api/suggest?q=" + encodeURIComponent(query), {}, 3000).catch(() => ({ suggestions: [] }));
    }

    standardsApi() {
        return this.fetchJson("/api/standards", {}, 10000);
    }

    treeApi(code) {
        return this.fetchJson("/api/tree?code=" + encodeURIComponent(code), {}, 8000);
    }

    clauseApi(code, clause, pos) {
        const params = new URLSearchParams({ code, clause });
        if (pos) params.set("pos", String(pos));
        return this.fetchJson("/api/clause?" + params.toString(), {}, 8000);
    }


    documentApi(code) {
        return this.fetchJson("/api/document?code=" + encodeURIComponent(code), {}, 15000);
    }

    changelogApi() {
        return this.fetchJson("/api/changelog", {}, 10000);
    }

    paramsApi(name) {
        const suffix = name ? "?name=" + encodeURIComponent(name) : "";
        return this.fetchJson("/api/params" + suffix, {}, 10000);
    }

    refsApi(code) {
        const suffix = code ? "?code=" + encodeURIComponent(code) : "";
        return this.fetchJson("/api/refs" + suffix, {}, 10000);
    }

    getServerDir() {
        const basePath = this.app.vault.adapter.basePath || "";
        return path.join(path.dirname(path.dirname(basePath)), "kb_core");
    }

    async startServer(options = {}) {
        if (this.serverProcess) {
            if (!options.silent) new Notice("知微 KB 后端已在本插件中运行");
            return true;
        }
        if (await this.checkBackend()) {
            if (!options.silent) new Notice("知微 KB 后端已可用");
            return true;
        }
        const serverDir = this.getServerDir();
        try {
            this.serverProcess = childProcess.spawn(this.settings.pythonCommand || "python", [path.join(serverDir, "server.py")], {
                cwd: serverDir,
                windowsHide: true,
                stdio: ["ignore", "pipe", "pipe"],
            });
            this.serverProcess.stdout.on("data", (data) => console.log("[Zhiwei KB]", data.toString().trim()));
            this.serverProcess.stderr.on("data", (data) => console.error("[Zhiwei KB]", data.toString().trim()));
            this.serverProcess.on("error", (error) => {
                if (!options.silent) new Notice("知微 KB 后端启动失败: " + error.message);
                this.serverProcess = null;
            });
            this.serverProcess.on("exit", () => {
                this.serverProcess = null;
            });
            await new Promise((resolve) => setTimeout(resolve, 1800));
            const ok = await this.checkBackend();
            if (!options.silent) new Notice(ok ? "知微 KB 后端已启动" : "进程已启动，后端仍在加载");
            return ok;
        } catch (error) {
            if (!options.silent) new Notice("知微 KB 后端启动失败: " + error.message);
            return false;
        }
    }

    async stopServer(options = {}) {
        const serverScript = path.join(this.getServerDir(), "server.py");
        const psCommand = "$script='" + serverScript.replace(/'/g, "''") + "'; " +
            "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" | " +
            "Where-Object { $_.CommandLine -and $_.CommandLine -like ('*' + $script + '*') } | " +
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }";
        try {
            if (this.serverProcess) {
                try { this.serverProcess.kill(); } catch {}
                this.serverProcess = null;
            }
            await new Promise((resolve) => {
                childProcess.execFile("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", psCommand], { windowsHide: true }, () => resolve());
            });
            if (!options.silent) new Notice("已停止知微 KB 后端");
        } catch (error) {
            if (!options.silent) new Notice("停止知微 KB 后端失败: " + error.message);
        }
    }
}

class ZhiweiEvidenceView extends ItemView {
    constructor(leaf, plugin) {
        super(leaf);
        this.plugin = plugin;
        this.activeTab = "search";
        this.searchTimer = null;
        this.standardsCache = null;
        this.changelogCache = null;
        this.paramsCache = null;
        this.refsSummaryCache = null;
        this.currentResults = [];
    }

    getViewType() { return VIEW_TYPE; }
    getDisplayText() { return "知微规范证据台"; }
    getIcon() { return "book-open-check"; }

    async onOpen() {
        const root = this.containerEl.children[1];
        root.empty();
        root.addClass("zhiwei-kb-root");
        this.injectStyles();

        this.headerEl = root.createDiv({ cls: "zk-header" });
        const titleWrap = this.headerEl.createDiv({ cls: "zk-title-wrap" });
        titleWrap.createDiv({ cls: "zk-title", text: "知微规范证据台" });
        this.statusEl = titleWrap.createDiv({ cls: "zk-status", text: "连接中..." });
        const controls = this.headerEl.createDiv({ cls: "zk-controls" });
        this.addIconButton(controls, "refresh-cw", "刷新状态", "刷新", () => this.checkStatus());
        this.addIconButton(controls, "power", "启动后端", "启动", () => this.startBackend());
        this.addIconButton(controls, "circle-stop", "停止知微后端", "停止", async () => { await this.plugin.stopServer(); this.checkStatus(); });

        this.tabsEl = root.createDiv({ cls: "zk-tabs" });
        this.contentEl = root.createDiv({ cls: "zk-content" });
        this.detailEl = root.createDiv({ cls: "zk-detail" });

        this.renderTabs();
        await this.renderActiveTab();
        this.checkStatus();
    }

    setQuery(query) {
        this.activeTab = "search";
        this.renderTabs();
        this.renderActiveTab().then(() => {
            this.searchInput.value = query;
            this.executeSearch();
        });
    }

    injectStyles() {
        if (document.getElementById("zhiwei-kb-styles")) return;
        const style = document.createElement("style");
        style.id = "zhiwei-kb-styles";
        style.textContent = `
            .zhiwei-kb-root { display:flex; flex-direction:column; height:100%; overflow:hidden; background:var(--background-primary); }
            .zk-header { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:10px 10px 8px; border-bottom:1px solid var(--background-modifier-border); }
            .zk-title { font-size:14px; font-weight:700; color:var(--text-normal); }
            .zk-status { margin-top:2px; font-size:11px; color:var(--text-muted); }
            .zk-controls { display:flex; gap:4px; }
            .zk-icon-btn { min-height:26px; display:flex; align-items:center; justify-content:center; gap:4px; border:1px solid var(--background-modifier-border); border-radius:4px; background:var(--background-secondary); color:var(--text-muted); cursor:pointer; padding:4px 7px; font-size:12px; white-space:nowrap; }
            .zk-icon-btn svg { width:14px; height:14px; flex:0 0 auto; }
            .zk-icon-btn:hover { color:var(--text-normal); background:var(--background-modifier-hover); }
            .zk-tabs { display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:4px; padding:8px 10px; border-bottom:1px solid var(--background-modifier-border); }
            .zk-tab { border:1px solid var(--background-modifier-border); border-radius:4px; padding:5px 4px; background:var(--background-secondary); color:var(--text-muted); cursor:pointer; font-size:12px; text-align:center; }
            .zk-tab.is-active { color:var(--text-on-accent); background:var(--interactive-accent); border-color:var(--interactive-accent); }
            .zk-content { flex:1; overflow:auto; padding:10px; }
            .zk-detail { max-height:22%; overflow:auto; border-top:1px solid var(--background-modifier-border); padding:8px 10px; background:var(--background-secondary); }
            .zk-detail:empty { display:none; }
            .zk-detail.is-clickable { cursor:pointer; }
            .zk-detail.is-clickable:hover { background:var(--background-modifier-hover); }
            .zk-input-row { display:flex; gap:6px; align-items:center; margin-bottom:8px; }
            .zk-input { flex:1; width:100%; box-sizing:border-box; border:1px solid var(--background-modifier-border); border-radius:4px; background:var(--background-primary); color:var(--text-normal); padding:7px 8px; font-size:13px; }
            .zk-select { border:1px solid var(--background-modifier-border); border-radius:4px; background:var(--background-primary); color:var(--text-normal); padding:6px; font-size:12px; }
            .zk-btn { border:1px solid var(--background-modifier-border); border-radius:4px; background:var(--background-secondary); color:var(--text-normal); padding:6px 8px; font-size:12px; cursor:pointer; }
            .zk-btn:hover { background:var(--background-modifier-hover); }
            .zk-muted { color:var(--text-muted); font-size:12px; }
            .zk-card { border:1px solid var(--background-modifier-border); border-radius:6px; padding:8px; margin-bottom:8px; background:var(--background-primary); cursor:pointer; }
            .zk-card:hover { border-color:var(--interactive-accent); background:var(--background-modifier-hover); }
            .zk-card-title { font-size:13px; font-weight:700; color:var(--interactive-accent); margin-bottom:3px; }
            .zk-code { font-size:11px; font-weight:700; color:var(--interactive-accent); }
            .zk-snippet { font-size:12px; line-height:1.45; color:var(--text-muted); margin-top:4px; white-space:pre-wrap; }
            .zk-actions { display:flex; gap:5px; flex-wrap:wrap; margin-top:7px; }
            .zk-meta-grid { display:flex; flex-wrap:wrap; gap:4px; margin:5px 0 6px; font-weight:700; color:var(--text-normal); }
            .zk-pill { display:inline-flex; align-items:center; gap:4px; border-radius:4px; background:var(--background-secondary); color:var(--text-normal); padding:2px 5px; font-size:10px; margin-right:4px; font-weight:700; }
            .zk-group-title { font-size:12px; font-weight:700; color:var(--text-muted); margin:12px 0 6px; }
            .zk-list-row { display:flex; align-items:flex-start; justify-content:space-between; gap:8px; border-bottom:1px solid var(--background-modifier-border); padding:7px 2px; font-size:12px; cursor:pointer; }
            .zk-list-row:hover { background:var(--background-modifier-hover); }
            .zk-row-main { min-width:0; flex:1; }
            .zk-row-side { flex:0 0 auto; color:var(--text-muted); font-size:11px; }
            .zk-tree-row { display:flex; gap:6px; align-items:baseline; padding:4px 3px; border-radius:4px; cursor:pointer; font-size:12px; }
            .zk-tree-row:hover { background:var(--background-modifier-hover); }
            .zk-detail-title { font-size:12px; font-weight:700; margin-bottom:4px; color:var(--text-normal); }
            .zk-clause-text { white-space:pre-wrap; line-height:1.45; font-size:12px; color:var(--text-normal); }
            .zk-suggest { display:flex; flex-wrap:wrap; gap:4px; margin-bottom:8px; }
            .zk-suggestion { border:1px solid var(--background-modifier-border); border-radius:4px; padding:3px 6px; font-size:11px; cursor:pointer; color:var(--text-muted); }
            .zk-suggestion:hover { color:var(--text-normal); background:var(--background-modifier-hover); }
        `;
        document.head.appendChild(style);
    }

    renderTabs() {
        this.tabsEl.empty();
        const tabs = [
            ["search", "检索"],
            ["standards", "标准库"],
            ["params", "参数"],
            ["refs", "引用"],
            ["changelog", "更新"],
        ];
        for (const [id, label] of tabs) {
            const tab = this.tabsEl.createDiv({ cls: "zk-tab" + (this.activeTab === id ? " is-active" : ""), text: label });
            tab.addEventListener("click", () => {
                this.activeTab = id;
                this.renderTabs();
                this.renderActiveTab();
            });
        }
    }

    async renderActiveTab() {
        this.contentEl.empty();
        this.detailEl.empty();
        if (this.activeTab === "search") this.renderSearchTab();
        else if (this.activeTab === "standards") await this.renderStandardsTab();
        else if (this.activeTab === "params") await this.renderParamsTab();
        else if (this.activeTab === "refs") await this.renderRefsTab();
        else if (this.activeTab === "changelog") await this.renderChangelogTab();
    }

    addIconButton(parent, icon, tooltip, label, callback) {
        const btn = parent.createEl("button", { cls: "zk-icon-btn", attr: { "aria-label": tooltip, title: tooltip } });
        setIcon(btn, icon);
        btn.createSpan({ text: label });
        btn.addEventListener("click", callback);
        return btn;
    }

    addButton(parent, label, callback) {
        const button = parent.createEl("button", { cls: "zk-btn", text: label });
        button.addEventListener("click", callback);
        return button;
    }

    async checkStatus() {
        this.statusEl.setText("连接中...");
        const ok = await this.plugin.checkBackend();
        this.statusEl.setText(ok ? "后端可用" : "后端未连接");
        this.statusEl.style.color = ok ? "var(--color-green)" : "var(--color-red)";
        return ok;
    }

    async startBackend() {
        this.statusEl.setText("启动中...");
        await this.plugin.startServer();
        this.checkStatus();
    }

    renderSearchTab() {
        const row = this.contentEl.createDiv({ cls: "zk-input-row" });
        this.searchInput = row.createEl("input", { cls: "zk-input", attr: { type: "text", placeholder: "搜索规范、条款、参数或问题" } });
        this.maxSelect = row.createEl("select", { cls: "zk-select" });
        [5, 10, 20].forEach((n) => this.maxSelect.createEl("option", { text: `${n}条`, value: String(n) }));
        this.maxSelect.value = String(this.plugin.settings.maxResults);
        this.addButton(row, "搜索", () => this.executeSearch());
        this.suggestEl = this.contentEl.createDiv({ cls: "zk-suggest" });
        this.searchMetaEl = this.contentEl.createDiv({ cls: "zk-muted" });
        this.resultsEl = this.contentEl.createDiv();
        this.searchInput.addEventListener("input", () => this.onSearchInput());
        this.searchInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") this.executeSearch();
        });
        this.resultsEl.createDiv({ cls: "zk-muted", text: "输入关键词开始检索。可以搜标准号、分项工程、参数要求、施工问题。" });
        setTimeout(() => this.searchInput.focus(), 100);
    }

    onSearchInput() {
        const query = this.searchInput.value.trim();
        clearTimeout(this.searchTimer);
        if (query.length < 2) {
            this.suggestEl.empty();
            return;
        }
        this.searchTimer = setTimeout(async () => {
            const data = await this.plugin.suggestApi(query);
            this.renderSuggestions(data.suggestions || []);
            this.executeSearch();
        }, 450);
    }

    renderSuggestions(items) {
        this.suggestEl.empty();
        items.slice(0, 8).forEach((item) => {
            const chip = this.suggestEl.createDiv({ cls: "zk-suggestion", text: item.text });
            chip.addEventListener("click", () => {
                this.searchInput.value = item.text;
                this.executeSearch();
            });
        });
    }

    async executeSearch() {
        const query = this.searchInput.value.trim();
        if (!query) return;
        this.resultsEl.empty();
        this.detailEl.empty();
        this.searchMetaEl.setText("检索中...");
        try {
            const data = await this.plugin.searchApi(query, Number(this.maxSelect.value));
            this.currentResults = data.results || [];
            this.searchMetaEl.setText(`找到 ${this.currentResults.length} 条结果` + (data.took_ms ? `，耗时 ${data.took_ms}ms` : ""));
            this.renderSearchResults(this.currentResults);
        } catch (error) {
            this.searchMetaEl.setText("");
            this.resultsEl.createDiv({ cls: "zk-muted", text: "检索失败: " + error.message });
        }
    }

    renderSearchResults(items) {
        this.resultsEl.empty();
        if (!items.length) {
            this.resultsEl.createDiv({ cls: "zk-muted", text: "没有匹配结果。可以换成标准号或更具体的施工术语。" });
            return;
        }
        items.forEach((item, index) => this.renderResultCard(this.resultsEl, item, index + 1));
    }

    truncatePreview(text, maxLength) {
        const clean = String(text || "").replace(/\s+/g, " ").trim();
        return clean.length > maxLength ? clean.substring(0, maxLength) + "..." : clean;
    }

    confidenceLabel(value) {
        const map = { high: "高", mid: "中", low: "低", medium: "中" };
        if (value && map[value]) return map[value];
        if (value) return value;
        return "低";
    }

    renderResultMeta(parent, item, fallbackRank) {
        parent.createSpan({ cls: "zk-pill", text: "排名：" + (item.rank || fallbackRank) });
        if (item.score !== undefined) parent.createSpan({ cls: "zk-pill", text: "分数：" + item.score });
        parent.createSpan({ cls: "zk-pill", text: "可信度：" + this.confidenceLabel(item.confidence) });
        if (item.source) parent.createSpan({ cls: "zk-pill", text: "来源：" + item.source });
        if (item.route) parent.createSpan({ cls: "zk-pill", text: "路由：" + item.route });
        if (item.confidence_meta && item.confidence_meta.query_coverage !== undefined) parent.createSpan({ cls: "zk-pill", text: "覆盖：" + item.confidence_meta.query_coverage });
        if (item.pos) parent.createSpan({ cls: "zk-pill", text: "位置：" + item.pos });
    }

    renderResultCard(parent, item, fallbackRank) {
        const card = parent.createDiv({ cls: "zk-card" });
        const code = item.code || this.extractCode(item.file || "") || "";
        const title = this.displayResultTitle(item);
        const titleEl = card.createDiv({ cls: "zk-card-title", text: title });
        titleEl.title = item.file || "";
        const meta = card.createDiv({ cls: "zk-meta-grid" });
        this.renderResultMeta(meta, item, fallbackRank);
        card.createDiv({ cls: "zk-snippet", text: this.truncatePreview(item.text || "", 220) });
        card.addEventListener("click", () => this.openResult(item));
    }

    displayResultTitle(item) {
        const fileName = String(item?.file || "").replace(/\.md$/i, "");
        let name = fileName.replace(/^_seg\d+_/, "").replace(/^_seg_/, "").replace(/_seg_/g, "").trim();
        if (name && item?.code && name.startsWith(item.code)) {
            name = name.slice(item.code.length).trim();
        }
        return name || item?.heading || fileName || "搜索结果";
    }

    extractCode(text) {
        const match = String(text || "").match(/(GB|JGJ|CJJ|CECS|TCECS|DB\d*|CJ|JTG|JTJ|TB|DL|SL|SH|SY|HG|YB|JG)[\sT/_]?(\d+(?:\.\d+)?(?:-\d+)?)/);
        return match ? (match[1] + match[2]).replace(/\s/g, "").replace("_", "/") : "";
    }

    extractClause(heading) {
        const match = String(heading || "").match(/(\d+(?:\.\d+)+|[A-Z]\.\d+|[Ⅰ-Ⅻ]+|[IVXLCDM]+)/);
        return match ? match[1] : "";
    }

    async previewResult(item) {
        const code = item.code || this.extractCode(item.file || "");
        const clause = this.extractClause(item.heading);
        if (code && clause) {
            await this.openClause(code, clause, item.pos || 0, item);
            return;
        }
        await this.openVaultFile(item.file || "", item.heading || "", code, item.pos || 0);
    }

    async previewClause(code, clause, pos, sourceItem) {
        await this.openClause(code, clause, pos, sourceItem);
    }

    async openResult(item) {
        const code = item.code || this.extractCode(item.file || "");
        const clause = this.extractClause(item.heading);
        if (code && clause) {
            await this.openClause(code, clause, item.pos || 0, item);
            return;
        }
        await this.openVaultFile(item.file || "", item.heading || "", code, item.pos || 0);
    }

    composeClauseHeading(clause, heading) {
        const cleanClause = String(clause || "").trim();
        const cleanHeading = String(heading || "").trim();
        if (!cleanClause) return cleanHeading;
        if (!cleanHeading) return cleanClause;
        return cleanHeading.startsWith(cleanClause) ? cleanHeading : cleanClause + " " + cleanHeading;
    }

    async openClause(code, clause, pos, sourceItem) {
        try {
            const data = await this.plugin.clauseApi(code, clause, pos);
            const targetHeading = this.composeClauseHeading(data.clause || clause, data.heading || sourceItem?.heading || "");
            await this.openVaultFile(data.file || sourceItem?.file || "", targetHeading, data.code || code, data.pos || sourceItem?.pos || pos || 0);
        } catch (error) {
            await this.openVaultFile(sourceItem?.file || "", this.composeClauseHeading(clause, sourceItem?.heading || ""), code, sourceItem?.pos || pos || 0);
        }
    }

    async renderStandardsTab() {
        this.contentEl.createDiv({ cls: "zk-muted", text: "加载标准库..." });
        try {
            if (!this.standardsCache) this.standardsCache = await this.plugin.standardsApi();
            this.contentEl.empty();
            const filterRow = this.contentEl.createDiv({ cls: "zk-input-row" });
            const filter = filterRow.createEl("input", { cls: "zk-input", attr: { placeholder: "筛选标准号或名称" } });
            const list = this.contentEl.createDiv();
            const render = () => this.renderStandardsList(list, this.standardsCache.groups || [], filter.value.trim());
            filter.addEventListener("input", render);
            render();
        } catch (error) {
            this.contentEl.empty();
            this.contentEl.createDiv({ cls: "zk-muted", text: "标准库加载失败: " + error.message });
        }
    }

    renderStandardsList(parent, groups, filterText) {
        parent.empty();
        const needle = filterText.toLowerCase();
        groups.forEach((group) => {
            const items = (group.items || []).filter((item) => !needle || `${item.code} ${item.name}`.toLowerCase().includes(needle));
            if (!items.length) return;
            parent.createDiv({ cls: "zk-group-title", text: `${group.label || group.prefix} (${items.length})` });
            items.slice(0, 80).forEach((item) => {
                const card = parent.createDiv({ cls: "zk-card" });
                card.createDiv({ cls: "zk-code", text: item.code || "" });
                card.createDiv({ cls: "zk-card-title", text: item.name || item.code || "未命名标准" });
                card.createDiv({ cls: "zk-muted", text: `${item.count || 0} 条款，${item.segments || 1} 分段` });
                const actions = card.createDiv({ cls: "zk-actions" });
                this.addButton(actions, "目录", (event) => { event.stopPropagation(); this.showStandardTree(item.code); });
                this.addButton(actions, "全文", (event) => { event.stopPropagation(); this.openDocumentPreview(item.code); });
                this.addButton(actions, "打开", (event) => { event.stopPropagation(); this.openVaultFile("", "", item.code); });
                card.addEventListener("click", () => this.showStandardTree(item.code));
            });
        });
    }

    async renderParamsTab() {
        this.contentEl.createDiv({ cls: "zk-muted", text: "加载参数索引..." });
        try {
            if (!this.paramsCache) this.paramsCache = await this.plugin.paramsApi();
            this.contentEl.empty();
            const row = this.contentEl.createDiv({ cls: "zk-input-row" });
            const filter = row.createEl("input", { cls: "zk-input", attr: { placeholder: "筛选参数名称，如混凝土强度等级" } });
            const list = this.contentEl.createDiv();
            const render = () => this.renderParamNames(list, this.paramsCache.params || [], filter.value.trim());
            filter.addEventListener("input", render);
            render();
        } catch (error) {
            this.contentEl.empty();
            this.contentEl.createDiv({ cls: "zk-muted", text: "参数索引加载失败: " + error.message });
        }
    }

    renderParamNames(parent, names, filterText) {
        parent.empty();
        const needle = filterText.toLowerCase();
        const items = names.filter((name) => !needle || name.toLowerCase().includes(needle));
        if (!items.length) {
            parent.createDiv({ cls: "zk-muted", text: "没有匹配的参数名称。" });
            return;
        }
        items.forEach((name) => {
            const row = parent.createDiv({ cls: "zk-list-row" });
            row.createDiv({ cls: "zk-row-main", text: name });
            row.createDiv({ cls: "zk-row-side", text: "查看" });
            row.addEventListener("click", () => this.showParamEntries(name));
        });
    }

    async showParamEntries(name) {
        this.detailEl.empty();
        this.detailEl.createDiv({ cls: "zk-detail-title", text: name });
        const body = this.detailEl.createDiv({ cls: "zk-clause-text", text: "加载参数条目..." });
        try {
            const data = await this.plugin.paramsApi(name);
            body.empty();
            body.createDiv({ cls: "zk-muted", text: `共 ${data.total || 0} 条，显示前 ${(data.entries || []).length} 条` });
            (data.entries || []).forEach((entry) => {
                const row = body.createDiv({ cls: "zk-list-row" });
                const main = row.createDiv({ cls: "zk-row-main" });
                main.createDiv({ cls: "zk-code", text: `${entry.std_code || ""} ${entry.clause || ""}`.trim() });
                main.createDiv({ text: `${entry.value || ""} ${entry.condition || ""}`.trim() || "未记录值" });
                if (entry.heading) main.createDiv({ cls: "zk-muted", text: entry.heading });
                row.addEventListener("click", () => {
                    if (entry.clause) this.openClause(entry.std_code || "", entry.clause, 0, { heading: entry.heading || "" });
                    else this.openVaultFile("", entry.heading || "", entry.std_code || "");
                });
            });
        } catch (error) {
            body.setText("参数条目加载失败: " + error.message);
        }
    }

    async renderRefsTab() {
        this.contentEl.createDiv({ cls: "zk-muted", text: "加载引用索引..." });
        try {
            if (!this.refsSummaryCache) this.refsSummaryCache = await this.plugin.refsApi();
            this.contentEl.empty();
            this.contentEl.createDiv({ cls: "zk-muted", text: `已索引 ${this.refsSummaryCache.total_refs || 0} 条引用，覆盖 ${this.refsSummaryCache.total_codes || 0} 个规范编号。` });
            const row = this.contentEl.createDiv({ cls: "zk-input-row" });
            const input = row.createEl("input", { cls: "zk-input", attr: { placeholder: "输入规范号，如 GB50204-2015" } });
            this.addButton(row, "查询", () => this.showRefs(input.value.trim()));
            input.addEventListener("keydown", (event) => { if (event.key === "Enter") this.showRefs(input.value.trim()); });
        } catch (error) {
            this.contentEl.empty();
            this.contentEl.createDiv({ cls: "zk-muted", text: "引用索引加载失败: " + error.message });
        }
    }

    async showRefs(code) {
        if (!code) return;
        this.detailEl.empty();
        this.detailEl.createDiv({ cls: "zk-detail-title", text: `${code} 引用关系` });
        const body = this.detailEl.createDiv({ cls: "zk-clause-text", text: "加载引用关系..." });
        try {
            const data = await this.plugin.refsApi(code);
            body.empty();
            this.renderRefGroup(body, "被这些规范引用", data.refs_by || []);
            this.renderRefGroup(body, "引用了这些规范", data.refs_to || []);
        } catch (error) {
            body.setText("引用关系加载失败: " + error.message);
        }
    }

    renderRefGroup(parent, title, items) {
        parent.createDiv({ cls: "zk-group-title", text: `${title} (${items.length})` });
        if (!items.length) {
            parent.createDiv({ cls: "zk-muted", text: "暂无记录。" });
            return;
        }
        items.forEach((item) => {
            const row = parent.createDiv({ cls: "zk-list-row" });
            row.createDiv({ cls: "zk-row-main", text: item.code || "" });
            row.createDiv({ cls: "zk-row-side", text: "打开" });
            row.addEventListener("click", () => this.openVaultFile("", "", item.code || ""));
        });
    }

    async renderChangelogTab() {
        this.contentEl.createDiv({ cls: "zk-muted", text: "加载最近更新..." });
        try {
            if (!this.changelogCache) this.changelogCache = await this.plugin.changelogApi();
            this.contentEl.empty();
            this.contentEl.createDiv({ cls: "zk-muted", text: `共 ${this.changelogCache.total || 0} 个 Markdown 文件，显示最近 ${(this.changelogCache.entries || []).length} 个。` });
            (this.changelogCache.entries || []).forEach((entry) => this.renderChangelogEntry(this.contentEl, entry));
        } catch (error) {
            this.contentEl.empty();
            this.contentEl.createDiv({ cls: "zk-muted", text: "最近更新加载失败: " + error.message });
        }
    }

    renderChangelogEntry(parent, entry) {
        const row = parent.createDiv({ cls: "zk-list-row" });
        const main = row.createDiv({ cls: "zk-row-main" });
        main.createDiv({ cls: "zk-code", text: entry.code || "" });
        main.createDiv({ text: entry.name || entry.file || "未命名文档" });
        const date = entry.mtime ? new Date(entry.mtime * 1000).toLocaleDateString() : "";
        row.createDiv({ cls: "zk-row-side", text: entry.is_new ? "新增" : date });
        row.addEventListener("click", () => this.openVaultFile(entry.file || "", "", entry.code || ""));
    }

    async showStandardTree(code) {
        if (!code) return;
        this.detailEl.empty();
        this.detailEl.createDiv({ cls: "zk-detail-title", text: `${code} 条文目录` });
        const list = this.detailEl.createDiv({ cls: "zk-clause-text", text: "加载目录中..." });
        try {
            const data = await this.plugin.treeApi(code);
            list.empty();
            (data.tree || []).slice(0, 160).forEach((node) => {
                const row = list.createDiv({ cls: "zk-tree-row" });
                row.style.paddingLeft = `${Math.min(node.depth || 0, 5) * 12 + 3}px`;
                row.createSpan({ cls: "zk-code", text: node.number || "" });
                row.createSpan({ text: node.title || "" });
                row.addEventListener("click", () => this.previewClause(data.code || code, node.number, node.pos || 0));
            });
        } catch (error) {
            list.setText("目录加载失败: " + error.message);
        }
    }

    async openDocumentPreview(code) {
        this.detailEl.empty();
        this.detailEl.createDiv({ cls: "zk-detail-title", text: `${code} 全文预览` });
        const body = this.detailEl.createDiv({ cls: "zk-clause-text", text: "加载全文中..." });
        try {
            const data = await this.plugin.documentApi(code);
            const text = String(data.text || "").replace(/<a id="tx\d+"[^>]*><\/a>/g, "");
            body.setText(text.substring(0, 12000) + (text.length > 12000 ? "\n\n……全文较长，已截断预览。" : ""));
        } catch (error) {
            body.setText("全文加载失败: " + error.message);
        }
    }

    async openVaultFile(fileName, heading, code, pos = 0) {
        try {
            const files = this.app.vault.getMarkdownFiles();
            let target = null;
            if (fileName) {
                const cleaned = fileName.replace(/\.md$/, "");
                target = files.find((file) => file.path === fileName || file.path.includes(cleaned) || file.name === fileName);
            }
            if (!target && code) {
                const compact = code.replace(/[\s/_-]/g, "");
                target = files.find((file) => file.name.replace(/[\s/_-]/g, "").includes(compact));
            }
            if (!target && fileName) {
                const cleaned = fileName.replace(/^_seg\d+_/, "").replace(/\.md$/, "");
                target = files.find((file) => file.name.includes(cleaned));
            }
            if (!target) {
                new Notice("未找到对应 Markdown 文件");
                return;
            }
            const leaf = this.getMainMarkdownLeaf(target.path);
            await leaf.openFile(target, { active: true });
            this.app.workspace.setActiveLeaf(leaf, { focus: true });
            this.scrollToTarget(target.path, heading, pos);
        } catch (error) {
            new Notice("打开失败: " + error.message);
        }
    }

    getMainMarkdownLeaf(targetPath) {
        const isMainLeaf = (leaf) => !leaf.containerEl?.closest?.(".mod-left-split, .mod-right-split");
        const mainLeaves = this.app.workspace.getLeavesOfType("markdown").filter(isMainLeaf);
        return mainLeaves.find((leaf) => leaf.view?.file?.path === targetPath)
            || mainLeaves[0]
            || this.app.workspace.getLeaf("tab");
    }

    offsetToLine(text, offset) {
        const safeOffset = Math.max(0, Math.min(Number(offset) || 0, text.length));
        return text.slice(0, safeOffset).split("\n").length - 1;
    }

    scrollToTarget(filePath, heading, pos) {
        let attempts = 0;
        const tryScroll = () => {
            attempts += 1;
            const leaves = this.app.workspace.getLeavesOfType("markdown");
            for (const leaf of leaves) {
                const view = leaf.view;
                if (!view || !view.file || view.file.path !== filePath || typeof view.getViewData !== "function") continue;
                if (pos > 0 && this.scrollToPositionInView(view, pos, heading)) return;
                if (heading && this.scrollToHeadingInView(view, heading, 0)) return;
            }
            if (attempts < 8) setTimeout(tryScroll, 150);
        };
        setTimeout(tryScroll, 120);
    }

    scrollViewToLine(view, line, totalLines) {
        const lastLine = Math.max(0, totalLines - 1);
        const targetLine = Math.max(0, Math.min(Number(line) || 0, lastLine));
        const mode = typeof view.getMode === "function" ? view.getMode() : "source";
        if (mode === "source" && view.editor) {
            view.editor.setCursor({ line: targetLine, ch: 0 });
            view.editor.scrollIntoView({ from: { line: Math.max(0, targetLine - 2), ch: 0 }, to: { line: Math.min(targetLine + 6, lastLine), ch: 0 } }, 120);
            return;
        }
        // Reading/preview mode: scroll the active renderer. Preview rendering is
        // async, so reapply a couple of times to make sure the scroll lands.
        if (view.currentMode && typeof view.currentMode.applyScroll === "function") {
            view.currentMode.applyScroll(targetLine);
            setTimeout(() => view.currentMode.applyScroll(targetLine), 200);
            setTimeout(() => view.currentMode.applyScroll(targetLine), 500);
            return;
        }
        if (typeof view.setEphemeralState === "function") {
            view.setEphemeralState({ line: targetLine });
        }
    }

    scrollToPositionInView(view, pos, heading = "") {
        const textValue = view.getViewData();
        const lines = textValue.split("\n");
        const posLine = this.offsetToLine(textValue, pos);
        const line = heading ? this.findHeadingNearLine(lines, heading, posLine) ?? posLine : posLine;
        this.scrollViewToLine(view, line, lines.length);
        return true;
    }

    findHeadingNearLine(lines, heading, posLine) {
        const needle = String(heading || "").replace(/[#\[\]]/g, "").trim();
        const clauseMatch = needle.match(/^(\d+(?:\.\d+)+|[A-Z]\.\d+|[Ⅰ-Ⅻ]+|[IVXLCDM]+)/);
        const clause = clauseMatch ? clauseMatch[1] : "";
        const normalizedNeedle = needle.replace(/\s+/g, "");
        const startLine = Math.max(0, posLine - 8);
        const endLine = Math.min(lines.length - 1, posLine + 30);
        const candidates = [];
        for (let line = startLine; line <= endLine; line++) {
            const raw = lines[line].trim();
            if (!raw.startsWith("#")) continue;
            const clean = raw.replace(/^#+\s*/, "").trim();
            const normalizedClean = clean.replace(/\s+/g, "");
            if (clean === needle || normalizedClean === normalizedNeedle) candidates.push({ line, score: 100 });
            else if (clause && clean.startsWith(clause + " ")) candidates.push({ line, score: 90 });
        }
        if (!candidates.length) return null;
        candidates.sort((a, b) => b.score - a.score || Math.abs(a.line - posLine) - Math.abs(b.line - posLine));
        return candidates[0].line;
    }

    scrollToHeadingInView(view, heading, pos = 0) {
        const textValue = view.getViewData();
        const lines = textValue.split("\n");
        const needle = String(heading || "").replace(/[#\[\]]/g, "").trim();
        if (!needle) return false;
        const clauseMatch = needle.match(/^(\d+(?:\.\d+)+|[A-Z]\.\d+|[Ⅰ-Ⅻ]+|[IVXLCDM]+)/);
        const clause = clauseMatch ? clauseMatch[1] : "";
        const normalizedNeedle = needle.replace(/\s+/g, "");
        const posLine = pos > 0 ? this.offsetToLine(textValue, pos) : 0;
        const startLine = pos > 0 ? Math.max(0, posLine - 6) : 0;
        const endLine = pos > 0 ? Math.min(lines.length - 1, posLine + 80) : lines.length - 1;
        const candidates = [];
        for (let line = startLine; line <= endLine; line++) {
            const raw = lines[line].trim();
            if (!raw.startsWith("#")) continue;
            const clean = raw.replace(/^#+\s*/, "").trim();
            const normalizedClean = clean.replace(/\s+/g, "");
            if (clean === needle || normalizedClean === normalizedNeedle) candidates.push({ line, score: 100 });
            else if (clause && clean.startsWith(clause + " ")) candidates.push({ line, score: 90 });
            else if (!clause && normalizedClean.includes(normalizedNeedle)) candidates.push({ line, score: 60 });
        }
        if (!candidates.length && pos > 0) {
            const fallbackLine = Math.max(0, Math.min(posLine, lines.length - 1));
            this.scrollViewToLine(view, fallbackLine, lines.length);
            return true;
        }
        if (!candidates.length) return false;
        candidates.sort((a, b) => b.score - a.score || Math.abs(a.line - posLine) - Math.abs(b.line - posLine));
        this.scrollViewToLine(view, candidates[0].line, lines.length);
        return true;
    }

    scrollToPosition(filePath, pos) {

        this.scrollToTarget(filePath, "", pos);
    }

    scrollToHeading(filePath, heading) {
        this.scrollToTarget(filePath, heading, 0);
    }
}

class ZhiweiSettingTab extends PluginSettingTab {
    constructor(app, plugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display() {
        const { containerEl } = this;
        containerEl.empty();
        containerEl.createEl("h2", { text: "知微规范证据台设置" });

        new Setting(containerEl)
            .setName("API 地址")
            .setDesc("知微 KB FastAPI 服务地址。")
            .addText((text) => text
                .setPlaceholder("http://localhost:8765")
                .setValue(this.plugin.settings.apiBase)
                .onChange(async (value) => {
                    this.plugin.settings.apiBase = value.trim() || DEFAULT_SETTINGS.apiBase;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName("Python 命令")
            .setDesc("用于从插件启动后端。")
            .addText((text) => text
                .setPlaceholder("python")
                .setValue(this.plugin.settings.pythonCommand)
                .onChange(async (value) => {
                    this.plugin.settings.pythonCommand = value.trim() || DEFAULT_SETTINGS.pythonCommand;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName("启动 Obsidian 时打开面板")
            .addToggle((toggle) => toggle
                .setValue(this.plugin.settings.autoOpen)
                .onChange(async (value) => {
                    this.plugin.settings.autoOpen = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName("启动 Obsidian 时尝试启动后端")
            .setDesc("只启动 server.py，不会杀掉其他 Python 进程。")
            .addToggle((toggle) => toggle
                .setValue(this.plugin.settings.autoStartBackend)
                .onChange(async (value) => {
                    this.plugin.settings.autoStartBackend = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName("默认搜索结果数")
            .addSlider((slider) => slider
                .setLimits(5, 20, 5)
                .setValue(this.plugin.settings.maxResults)
                .setDynamicTooltip()
                .onChange(async (value) => {
                    this.plugin.settings.maxResults = value;
                    await this.plugin.saveSettings();
                }));
    }
}

module.exports = ZhiweiEvidencePlugin;
