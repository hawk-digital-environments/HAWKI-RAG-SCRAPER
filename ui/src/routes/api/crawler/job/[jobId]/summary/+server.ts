import { json } from '@sveltejs/kit';

import { crawlerApiBaseUrls } from '$lib/server/config';
import { fetchCrawler } from '$lib/server/crawler-client';

type SummaryCounts = {
	found: number;
	completed: number;
	missed: number;
};

function segmentEncode(pathname: string): string {
	return pathname
		.split('/')
		.filter(Boolean)
		.map((segment) => encodeURIComponent(segment))
		.join('/');
}

function safeNumber(value: unknown): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function deriveCounts(summary: unknown): SummaryCounts {
	if (!summary || typeof summary !== 'object') {
		return { found: 0, completed: 0, missed: 0 };
	}

	const urls = (summary as Record<string, unknown>).urls;
	if (!urls || typeof urls !== 'object') {
		return { found: 0, completed: 0, missed: 0 };
	}

	const found = safeNumber((urls as Record<string, unknown>).total);
	const completed = safeNumber((urls as Record<string, unknown>).completed);
	const failed = safeNumber((urls as Record<string, unknown>).failed);
	const missed = failed || Math.max(found - completed, 0);
	return { found, completed, missed };
}

export async function GET({ fetch, params }) {
	const { jobId } = params;
	if (!jobId) {
		return json({ error: 'jobId is required' }, { status: 400 });
	}

	try {
		const { response: filesResponse } = await fetchCrawler(
			fetch,
			`/jobs/${encodeURIComponent(jobId)}/files`
		);
		if (!filesResponse.ok) {
			return json({ found: false, summary: null, counts: null }, { status: 200 });
		}
		const filesPayload = await filesResponse.json();
		const files: Array<Record<string, unknown>> = Array.isArray(filesPayload?.files)
			? (filesPayload.files as Array<Record<string, unknown>>)
			: [];
		const summaryFile = files.find((file: Record<string, unknown>) => {
			const path = typeof file.path === 'string' ? file.path : '';
			return path.endsWith('summary.json');
		});

		if (!summaryFile || typeof summaryFile.path !== 'string') {
			return json({ found: false, summary: null, counts: null }, { status: 200 });
		}

		const encodedPath = segmentEncode(summaryFile.path);
		const { response: summaryResponse } = await fetchCrawler(
			fetch,
			`/jobs/${encodeURIComponent(jobId)}/files/${encodedPath}`
		);
		if (!summaryResponse.ok) {
			return json({ found: false, summary: null, counts: null }, { status: 200 });
		}
		const summary = await summaryResponse.json();
		const counts = deriveCounts(summary);

		return json({ found: true, summary, counts }, { status: 200 });
	} catch (error) {
		return json(
			{
				error: `Failed to load summary: ${error}`,
				hint: 'Check crawler container and restart it if needed: docker restart crawl4ai-service',
				attempted_endpoints: crawlerApiBaseUrls
			},
			{ status: 502 }
		);
	}
}
