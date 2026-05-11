<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { base } from '$app/paths';

	let { children } = $props();

	function isActive(path: string): boolean {
		if (path === '/') return $page.url.pathname === base || $page.url.pathname === `${base}/`;
		return $page.url.pathname.startsWith(`${base}${path}`);
	}
</script>

<div class="app">
	<aside class="sidebar">
		<div class="sidebar-header">
			<div class="sidebar-title">RAG Interface</div>
			<div class="sidebar-subtitle">Web Scraper Admin</div>
		</div>

		<nav class="sidebar-nav">
			<div class="sidebar-section">Monitor</div>
			<a href="{base}/" class="nav-link" class:active={isActive('/')}>
				<span class="icon">▶</span> Running Jobs
			</a>

			<div class="sidebar-section">Manage</div>
			<a
				href="{base}/profiles"
				class="nav-link"
				class:active={isActive('/profiles') && !isActive('/profiles/new')}
			>
				<span class="icon">◫</span> Profiles
			</a>
			<a
				href="{base}/tasks"
				class="nav-link"
				class:active={isActive('/tasks') && !isActive('/tasks/new')}
			>
				<span class="icon">☰</span> Tasks
			</a>

			<div class="nav-divider"></div>
			<div class="sidebar-section">Create</div>

			<a href="{base}/tasks/new" class="nav-link" class:active={isActive('/tasks/new')}>
				<span class="icon">+</span> New Task
			</a>
			<a
				href="{base}/profiles/new"
				class="nav-link"
				class:active={isActive('/profiles/new')}
			>
				<span class="icon">+</span> New Profile
			</a>
		</nav>
	</aside>

	<div class="main">
		{@render children()}
	</div>
</div>

<style>
	/* =========================================================
	   App shell — sidebar + main layout only.
	   All component styles live in their respective ui/ files.
	   ========================================================= */
	.app {
		display: flex;
		min-height: 100vh;
	}

	.sidebar {
		width: var(--sidebar-width);
		min-height: 100vh;
		background: var(--c-nav-bg);
		border-right: 1px solid var(--c-nav-border);
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		position: fixed;
		top: 0;
		left: 0;
		bottom: 0;
		overflow-y: auto;
		z-index: 10;
	}

	.sidebar-header {
		padding: 20px 16px 16px;
		border-bottom: 1px solid var(--c-nav-border);
	}

	.sidebar-title {
		font-size: 17px;
		font-weight: 700;
		color: #111827;
		letter-spacing: -0.01em;
	}

	.sidebar-subtitle {
		font-size: 13px;
		color: var(--c-nav-section);
		margin-top: 2px;
	}

	.sidebar-nav {
		padding: 12px 8px;
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.sidebar-section {
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--c-nav-section);
		padding: 10px 8px 4px;
	}

	.nav-link {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 9px 10px;
		border-radius: var(--radius-sm);
		color: var(--c-nav-text);
		font-size: 15px;
		font-weight: 500;
		text-decoration: none;
		transition: background 0.1s, color 0.1s;
	}

	.nav-link:hover {
		background: var(--c-nav-hover-bg);
		color: var(--c-nav-text);
		text-decoration: none;
	}

	.nav-link.active {
		background: var(--c-nav-active-bg);
		color: var(--c-nav-text-active);
		font-weight: 600;
	}

	.nav-link .icon {
		font-size: 14px;
		width: 18px;
		text-align: center;
		flex-shrink: 0;
		opacity: 0.7;
	}

	.nav-link.active .icon {
		opacity: 1;
	}

	.nav-divider {
		height: 1px;
		background: var(--c-nav-border);
		margin: 8px 4px;
	}

	.main {
		margin-left: var(--sidebar-width);
		flex: 1;
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}

</style>
