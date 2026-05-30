<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	type Props = {
		class?: string;
		children?: Snippet;
	} & HTMLAttributes<HTMLDivElement>;

	let { class: className = '', children, ...rest }: Props = $props();
</script>

<div class={cn('rounded-xl border bg-card text-card-foreground shadow', className)} {...rest}>
	{@render children?.()}
</div>
