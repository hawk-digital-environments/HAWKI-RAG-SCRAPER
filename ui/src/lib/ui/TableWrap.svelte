<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();
</script>

<div class="table-wrap">{@render children()}</div>

<style>
	.table-wrap {
		overflow-x: auto;
	}

	.table-wrap :global(table) {
		width: 100%;
		border-collapse: collapse;
		font-size: 15px;
	}

	.table-wrap :global(thead th) {
		text-align: left;
		padding: 10px 16px;
		font-size: 13px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--c-text-muted);
		background: var(--c-border-subtle);
		border-bottom: 1px solid var(--c-border);
	}

	.table-wrap :global(tbody tr) {
		border-bottom: 1px solid var(--c-border-subtle);
		transition: background 0.08s;
	}

	.table-wrap :global(tbody tr:last-child) {
		border-bottom: none;
	}

	.table-wrap :global(tbody tr:hover) {
		background: #f8fafc;
	}

	.table-wrap :global(tbody tr.clickable) {
		cursor: pointer;
	}

	.table-wrap :global(td) {
		padding: 13px 16px;
		vertical-align: middle;
		color: var(--c-text);
	}

	.table-wrap :global(td.muted) {
		color: var(--c-text-muted);
	}

	.table-wrap :global(td.mono) {
		font-family: var(--font-mono);
		font-size: 12px;
	}

	.table-wrap :global(td.number) {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
</style>
