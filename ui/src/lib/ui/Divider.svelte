<script lang="ts">
	interface Props {
		spacing?: 'sm' | 'default' | 'lg';
	}

	let { spacing = 'default' }: Props = $props();
</script>

<hr class="divider divider-{spacing}" />

<style>
	.divider {
		border: none;
		border-top: 1px solid var(--c-border);
		margin: 0;
	}

	.divider-sm { margin: 16px 0; }
	.divider-default { margin: 28px 0; }
	.divider-lg { margin: 44px 0; }
</style>
