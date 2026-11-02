import { test } from 'node:test';
import assert from 'node:assert/strict';
import { latestRequest } from '../src/lib/latest-request.ts';

// the page's load(), with the network replaced by promises the test settles by hand
function screen() {
	const state = { active: 'A', data: null, error: null, loading: false };
	const tracker = latestRequest();
	async function load(fetchIt) {
		const id = state.active;
		const req = tracker.begin(id);
		state.data = null; state.error = null;
		state.loading = true;
		try {
			const r = await fetchIt(id);
			if (req.isCurrent(state.active)) state.data = r;
		} catch (e) {
			if (req.isCurrent(state.active)) state.error = e.message;
		} finally {
			if (req.isLatest()) state.loading = false;
		}
	}
	return { state, load };
}
const deferred = () => { let ok, no; const p = new Promise((a, b) => { ok = a; no = b; }); return { p, ok, no }; };

test('a late answer for the company just left is never shown', async () => {
	const { state, load } = screen();
	const a = deferred(), b = deferred();
	const pa = load(() => a.p);
	state.active = 'B';
	const pb = load(() => b.p);
	assert.equal(state.data, null);
	b.ok('B-data'); await pb;
	assert.equal(state.data, 'B-data'); assert.equal(state.loading, false);
	a.ok('A-data'); await pa;
	assert.equal(state.data, 'B-data', 'the late A answer did not replace B');
});

test('a late error for the old company neither shows nor clears the new one', async () => {
	const { state, load } = screen();
	const a = deferred(), b = deferred();
	const pa = load(() => a.p);
	state.active = 'B';
	const pb = load(() => b.p);
	a.no(new Error('A failed')); await pa;
	assert.equal(state.error, null); assert.equal(state.loading, true, 'B is still loading');
	b.ok('B-data'); await pb;
	assert.equal(state.data, 'B-data'); assert.equal(state.loading, false);
});

test('a quick refresh for the same company: only the newest answer counts', async () => {
	const { state, load } = screen();
	const first = deferred(), second = deferred();
	const p1 = load(() => first.p);
	const p2 = load(() => second.p);
	second.ok('new'); await p2;
	first.ok('old'); await p1;
	assert.equal(state.data, 'new');
});

test('company cleared while a request is in flight: nothing is shown', async () => {
	const { state, load } = screen();
	const a = deferred();
	const pa = load(() => a.p);
	state.active = '';
	await load(() => Promise.reject(new Error('never called')));
	a.ok('A-data'); await pa;
	assert.equal(state.data, null); assert.equal(state.loading, false);
});
