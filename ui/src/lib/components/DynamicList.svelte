<script lang="ts">
	import Button from '$lib/ui/Button.svelte';
	import TextInput from '$lib/ui/TextInput.svelte';

	interface Props {
		items: string[];
		onchange: (items: string[]) => void;
		placeholder?: string;
		addLabel?: string;
		inputType?: 'text' | 'url' | 'email' | 'search';
	}

	let { items, onchange, placeholder = 'Add value...', addLabel = 'Add', inputType = 'text' }: Props =
		$props();

	function update(index: number, value: string) {
		const next = [...items];
		next[index] = value;
		onchange(next);
	}

	function remove(index: number) {
		onchange(items.filter((_, i) => i !== index));
	}

	function add() {
		onchange([...items, '']);
	}
</script>

<div class="dynamic-list">
	{#each items as item, i}
		<div class="item-row">
			<TextInput
				type={inputType}
				value={item}
				{placeholder}
				oninput={(e) => update(i, (e.target as HTMLInputElement).value)}
			/>
			<Button variant="ghost" size="icon" type="button" title="Remove" onclick={() => remove(i)}>✕</Button>
		</div>
	{/each}

	<Button variant="ghost" size="sm" type="button" onclick={add}>+ {addLabel}</Button>
</div>

<style>
	.dynamic-list {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.item-row {
		display: flex;
		gap: 6px;
		align-items: center;
	}

	.item-row :global(.input) {
		flex: 1;
	}
</style>
