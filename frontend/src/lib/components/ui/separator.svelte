<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import { cn } from '$lib/utils';

	type Props = {
		orientation?: 'horizontal' | 'vertical';
		decorative?: boolean;
		class?: string;
	} & HTMLAttributes<HTMLDivElement>;

	let {
		orientation = 'horizontal',
		decorative = true,
		class: className = '',
		...rest
	}: Props = $props();
</script>

<div
	role={decorative ? 'none' : 'separator'}
	aria-orientation={orientation}
	class={cn(
		'shrink-0 bg-border',
		orientation === 'horizontal' ? 'h-[1px] w-full' : 'h-full w-[1px]',
		className
	)}
	{...rest}
/>
