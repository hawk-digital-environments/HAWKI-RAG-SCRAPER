<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		subtitle?: string;
		/** Breadcrumb links rendered above the title. */
		breadcrumb?: Snippet;
		/** Right-side action buttons. */
		actions?: Snippet;
	}

	let { title, subtitle, breadcrumb, actions }: Props = $props();
</script>

<!-- Title + subtitle rendered in the transparent/blue hero zone -->
<div class="header-hero">
	<h1 class="page-title">{title}</h1>
	{#if subtitle}<p class="page-subtitle">{subtitle}</p>{/if}
</div>

<!-- Breadcrumb + actions rendered in the white panel zone -->
<div class="header-panel">
	{#if breadcrumb}
		<div class="header-breadcrumb">{@render breadcrumb()}</div>
	{/if}
	{#if actions}
		<div class="page-actions">{@render actions()}</div>
	{/if}
</div>

<style>
	/* Hero zone: title + subtitle on the blue background.
	   Negative horizontal margins cancel the parent .page padding so the
	   zone stretches edge-to-edge across the full panel width. */
	.header-hero {
		margin: 0 -40px;
		padding: 28px 40px 24px;
		min-height: var(--page-hero-content-height);
		box-sizing: border-box;
		display: flex;
		flex-direction: column;
		justify-content: center;
	}

	.page-title {
		font-size: 30px;
		font-weight: 700;
		color: #ffffff;
	}

	.page-subtitle {
		font-size: 19px;
		color: rgba(255, 255, 255, 0.8);
		margin-top: 8px;
		line-height: 1.5;
		max-width: 480px;
	}

	/* Panel zone: breadcrumb on the left, action buttons on the right */
	.header-panel {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 24px 0 32px;
		gap: 16px;
	}

	.header-breadcrumb {
		flex: 1;
	}

	.page-actions {
		display: flex;
		gap: 10px;
		flex-shrink: 0;
		align-items: center;
	}
</style>
