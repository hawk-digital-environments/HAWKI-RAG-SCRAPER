import { env } from '$env/dynamic/private';

function splitUrls(value: string | undefined, fallback: string[]): string[] {
	const urls = value
		?.split(',')
		.map((item) => item.trim())
		.filter(Boolean);

	return urls?.length ? urls : fallback;
}

export const crawlerApiBaseUrls = splitUrls(env.CRAWLER_API_BASE_URL, [
	'http://127.0.0.1:8041',
	'http://localhost:8041',
	'http://127.0.0.1:8040',
	'http://localhost:8040',
	'http://127.0.0.1:8000',
	'http://localhost:8000'
]);

export const crawlerConnectionHint =
	'Use http://localhost:8041/ui/ for the Docker UI, or start the dev UI with make start-ui after the crawler is running. For dev UI overrides, set CRAWLER_API_BASE_URL=http://127.0.0.1:8041.';
