import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

import { crawlerApiBaseUrls } from '$lib/server/config';
import { fetchCrawler } from '$lib/server/crawler-client';

export const GET: RequestHandler = async ({ fetch }) => {
	try {
		const { response, url } = await fetchCrawler(fetch, '/jobs');
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
				error: `Failed to load jobs: ${error}`,
				hint: 'Check crawler container and restart it if needed: docker restart crawl4ai-service',
				attempted_endpoints: crawlerApiBaseUrls
			},
			{ status: 502 }
		);
	}
};
