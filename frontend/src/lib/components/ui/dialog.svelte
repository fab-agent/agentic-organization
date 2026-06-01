<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	type Props = {
		open?: boolean;
		label?: string;
		onOpenChange?: (open: boolean) => void;
		class?: string;
		children?: Snippet;
	};

	let {
		open = $bindable(false),
		label,
		onOpenChange,
		class: className = '',
		children,
		...rest
	}: Props = $props();

	let panelEl: HTMLElement | null = $state(null);
	let previousFocus: HTMLElement | null = null;

	$effect(() => {
		if (open) {
			previousFocus = document.activeElement as HTMLElement;
			setTimeout(() => getFocusable()[0]?.focus(), 10);
		} else {
			previousFocus?.focus();
			previousFocus = null;
		}
	});

	function getFocusable(): HTMLElement[] {
		if (!panelEl) return [];
		return Array.from(
			panelEl.querySelectorAll<HTMLElement>(
				'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
			)
		);
	}

	function handleClose() {
		open = false;
		onOpenChange?.(false);
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) handleClose();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			handleClose();
			return;
		}
		if (e.key !== 'Tab') return;

		const focusable = getFocusable();
		if (!focusable.length) return;
		const first = focusable[0];
		const last = focusable[focusable.length - 1];

		if (e.shiftKey) {
			if (document.activeElement === first) {
				e.preventDefault();
				last.focus();
			}
		} else {
			if (document.activeElement === last) {
				e.preventDefault();
				first.focus();
			}
		}
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 animate-backdrop"
		onclick={handleBackdropClick}
		onkeydown={handleKeydown}
		role="dialog"
		aria-modal="true"
		aria-label={label}
		tabindex="-1"
	>
		<div
			bind:this={panelEl}
			class={cn(
				'bg-background relative w-full max-w-lg rounded-xl border p-6 shadow-lg animate-dialog mx-4',
				className
			)}
			onclick={(e) => e.stopPropagation()}
			{...rest}
		>
			{@render children?.()}
		</div>
	</div>
{/if}
