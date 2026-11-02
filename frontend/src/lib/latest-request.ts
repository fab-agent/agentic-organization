/**
 * Only the newest request, for the key that is still current, may touch the screen.
 * A slow answer for the company you just left must neither be shown nor clear the new
 * company's loading/error state.
 */
export function latestRequest<K>() {
	let n = 0;
	return {
		begin(key: K) {
			const ticket = ++n;
			return {
				/** may this request's answer or error be shown for the key that is active now? */
				isCurrent: (activeKey: K) => ticket === n && key === activeKey,
				/** is it still the newest request (for the loading flag)? */
				isLatest: () => ticket === n
			};
		}
	};
}
