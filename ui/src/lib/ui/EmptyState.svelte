<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();
</script>

<div class="empty-state">{@render children()}</div>

<style>
	.empty-state {
		text-align: center;
		padding: 48px 24px;
		color: var(--c-text-muted);
		font-size: 15px;
	}

	/* Make links inside readable */
	.empty-state :global(a) {
		color: var(--c-primary);
	}
</style>
