import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fetchEndpoints } from '../src/lib/server/fetch-endpoints.js';

test('ambiguous mutation delivery never tries another runtime', async () => {
	/** @type {string[]} */
	const calls = [];
	await assert.rejects(fetchEndpoints(['http://a', 'http://b'], async (url) => {
		calls.push(String(url));
		throw new Error('accepted, response lost');
	}, '/crawl', { method: 'POST' }));
	assert.deepEqual(calls, ['http://a/crawl']);
});

test('status reads retain connection failover', async () => {
	/** @type {string[]} */
	const calls = [];
	const result = await fetchEndpoints(['http://a', 'http://b'], async (url) => {
		calls.push(String(url));
		if (String(url).startsWith('http://a/')) throw new Error('offline');
		return new Response('{}');
	}, '/status/job');
	assert.equal(result.url, 'http://b/status/job');
	assert.equal(calls.length, 2);
});
