<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	type Props = {
		open?: boolean;
		onOpenChange?: (open: boolean) => void;
		class?: string;
		children?: Snippet;
	};

	let {
		open = $bindable(false),
		onOpenChange,
		class: className = '',
		children,
		...rest
	}: Props = $props();

	function handleClose() {
		open = false;
		onOpenChange?.(false);
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			handleClose();
		}
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
		onclick={handleBackdropClick}
		onkeydown={(e) => {
			if (e.key === 'Escape') handleClose();
		}}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
	>
		<div
			class={cn(
				'bg-background relative w-full max-w-lg rounded-xl border p-6 shadow-lg duration-200',
				className
			)}
			onclick={(e) => e.stopPropagation()}
			{...rest}
		>
			{@render children?.()}
		</div>
	</div>
{/if}
