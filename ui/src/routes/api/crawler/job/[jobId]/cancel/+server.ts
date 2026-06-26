import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

import { crawlerApiBaseUrls, crawlerConnectionHint } from '$lib/server/config';
import { fetchCrawler } from '$lib/server/crawler-client';

export const POST: RequestHandler = async ({ fetch, params }) => {
	const { jobId } = params;
	if (!jobId) {
		return json({ error: 'jobId is required' }, { status: 400 });
	}

	try {
		const { response, url } = await fetchCrawler(
			fetch,
			`/jobs/${encodeURIComponent(jobId)}/cancel`,
			{ method: 'POST' }
		);
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
				error: `Cancel request failed: ${error}`,
				hint: crawlerConnectionHint,
				attempted_endpoints: crawlerApiBaseUrls
			},
			{ status: 502 }
		);
	}
};
