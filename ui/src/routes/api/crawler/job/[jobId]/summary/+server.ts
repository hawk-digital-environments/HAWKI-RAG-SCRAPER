import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

import { crawlerApiBaseUrls, crawlerConnectionHint } from '$lib/server/config';
import { fetchCrawler } from '$lib/server/crawler-client';

type SummaryCounts = {
	found: number;
	completed: number;
	missed: number;
};

type FileEntry = {
	path?: unknown;
};

type UrlChunkEntry = {
	status?: unknown;
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

function failedUrlsFromChunk(chunk: unknown): string[] {
	if (!chunk || typeof chunk !== 'object') return [];
	const urls: string[] = [];
	for (const [url, value] of Object.entries(chunk)) {
		const entry = value as UrlChunkEntry;
		if (entry && typeof entry === 'object' && entry.status === 'failed') {
			urls.push(url);
		}
	}
	return urls;
}

async function readFailedUrls(
	serverFetch: typeof globalThis.fetch,
	jobId: string,
	files: FileEntry[]
): Promise<string[]> {
	const chunkPaths = files
		.map((file) => (typeof file.path === 'string' ? file.path : ''))
		.filter((path) => path.startsWith('url_chunks/') && path.endsWith('.json'))
		.sort();

	const failedUrls: string[] = [];
	for (const chunkPath of chunkPaths) {
		const encodedPath = segmentEncode(chunkPath);
		const { response } = await fetchCrawler(
			serverFetch,
			`/jobs/${encodeURIComponent(jobId)}/files/${encodedPath}`
		);
		if (!response.ok) continue;

		try {
			failedUrls.push(...failedUrlsFromChunk(await response.json()));
		} catch {
			continue;
		}
	}

	return failedUrls;
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
			return json({ found: false, summary: null, counts: null }, { status: 200 });
		}
		const filesPayload = await filesResponse.json();
		const files: FileEntry[] = Array.isArray(filesPayload?.files)
			? (filesPayload.files as FileEntry[])
			: [];
		const summaryFile = files.find((file: FileEntry) => {
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
		const failedUrls = await readFailedUrls(fetch, jobId, files);

		return json({ found: true, summary, counts, failedUrls }, { status: 200 });
	} catch (error) {
		return json(
			{
				error: `Failed to load summary: ${error}`,
				hint: crawlerConnectionHint,
				attempted_endpoints: crawlerApiBaseUrls
			},
			{ status: 502 }
		);
	}
};
