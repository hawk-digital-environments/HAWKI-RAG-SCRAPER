<script lang="ts">
	interface Crumb {
		label: string;
		href?: string;
	}

	interface Props {
		items: Crumb[];
	}

	let { items }: Props = $props();
</script>

<nav class="breadcrumb" aria-label="Breadcrumb">
	{#each items as item, i}
		{#if i > 0}<span class="sep">/</span>{/if}
		{#if item.href && i < items.length - 1}
			<a href={item.href}>{item.label}</a>
		{:else}
			<span>{item.label}</span>
		{/if}
	{/each}
</nav>

<style>
	.breadcrumb {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 14px;
		color: var(--c-text-muted);
	}

	.breadcrumb a {
		color: var(--c-text-muted);
		text-decoration: none;
	}
	.breadcrumb a:hover {
		color: var(--c-primary);
		text-decoration: none;
	}

	.sep {
		color: var(--c-primary);
	}
</style>
