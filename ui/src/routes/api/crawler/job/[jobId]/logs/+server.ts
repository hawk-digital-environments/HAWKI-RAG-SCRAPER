import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

import { crawlerApiBaseUrls } from '$lib/server/config';
import { fetchCrawler } from '$lib/server/crawler-client';

function segmentEncode(pathname: string): string {
	return pathname
		.split('/')
		.filter(Boolean)
		.map((segment) => encodeURIComponent(segment))
		.join('/');
}

function isNoisyAccessLog(line: string): boolean {
	return (
		line.includes('"GET /jobs HTTP/1.1"') ||
		line.includes('"GET /health HTTP/1.1"') ||
		/"GET \/jobs(?:\?[^"]*)? HTTP\/1\.1"\s+200\s+OK/.test(line) ||
		/"GET \/health(?:\?[^"]*)? HTTP\/1\.1"\s+200\s+OK/.test(line)
	);
}

export const GET: RequestHandler = async ({ fetch, params }) => {
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
			return json({ found: false, lines: [] }, { status: 200 });
		}

		const filesPayload = await filesResponse.json();
		const files: Array<Record<string, unknown>> = Array.isArray(filesPayload?.files)
			? (filesPayload.files as Array<Record<string, unknown>>)
			: [];
		const logFile = files.find((file) => {
			const path = typeof file.path === 'string' ? file.path : '';
			return path.endsWith('crawler.log');
		});

		if (!logFile || typeof logFile.path !== 'string') {
			return json({ found: false, lines: [] }, { status: 200 });
		}

		const encodedPath = segmentEncode(logFile.path);
		const { response: logResponse } = await fetchCrawler(
			fetch,
			`/jobs/${encodeURIComponent(jobId)}/files/${encodedPath}`
		);
		if (!logResponse.ok) {
			return json({ found: false, lines: [] }, { status: 200 });
		}

		const text = await logResponse.text();
		const lines = text
			.split(/\r?\n/)
			.filter((line) => line.trim().length > 0)
			.filter((line) => !isNoisyAccessLog(line));

		return json({ found: true, lines }, { status: 200 });
	} catch (error) {
		return json(
			{
				error: `Failed to load job log: ${error}`,
				hint: 'Check crawler container and restart it if needed: docker restart crawl4ai-service',
				attempted_endpoints: crawlerApiBaseUrls
			},
			{ status: 502 }
		);
	}
};
