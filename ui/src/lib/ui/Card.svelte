<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title?: string;
		/** Renders in the card header's right slot (e.g. action buttons). */
		actions?: Snippet;
		/** When true, removes padding from the body — use for flush tables. */
		noPadding?: boolean;
		/** Optional footer snippet. */
		footer?: Snippet;
		children: Snippet;
	}

	let { title, actions, noPadding = false, footer, children }: Props = $props();
</script>

<div class="section">
	{#if title || actions}
		<div class="section-header">
			{#if title}<span class="section-title">{title}</span>{/if}
			{#if actions}{@render actions()}{/if}
		</div>
	{/if}

	<div class="section-body" class:no-padding={noPadding}>
		{@render children()}
	</div>

	{#if footer}
		<div class="section-footer">
			{@render footer()}
		</div>
	{/if}
</div>

<style>
	/* Sections are flat — no border, no shadow, no background box */
	.section {
		margin-top: 0;
	}

	.section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 28px 0 16px;
		gap: 12px;
	}

	.section-title {
		font-size: 16px;
		font-weight: 600;
		color: var(--c-text);
	}

	.section-body {
		padding: 0 0 28px;
	}

	.section-body.no-padding {
		padding: 0;
	}

	.section-footer {
		padding: 16px 0;
		border-top: 1px solid var(--c-border);
	}
</style>
