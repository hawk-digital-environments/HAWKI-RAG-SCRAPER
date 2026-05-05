import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

import { crawlerApiBaseUrls } from '$lib/server/config';
import { fetchCrawler } from '$lib/server/crawler-client';

export const POST: RequestHandler = async ({ request, fetch }) => {
	let payload: unknown;
	try {
		payload = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	try {
		const { response, url } = await fetchCrawler(fetch, '/crawl', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(payload)
		});
		const text = await response.text();
		return new Response(text, {
			status: response.status,
			headers: {
				'content-type': response.headers.get('content-type') ?? 'application/json',
				'x-crawler-upstream': url
			}
		});
	} catch (error) {
		return json(
			{
				error: `Crawler request failed: ${error}`,
				hint: 'Check crawler container and restart it if needed: docker restart crawl4ai-service',
				attempted_endpoints: crawlerApiBaseUrls
			},
			{ status: 502 }
		);
	}
};
