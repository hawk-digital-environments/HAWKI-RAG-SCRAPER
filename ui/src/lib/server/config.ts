import { env } from '$env/dynamic/private';

function splitUrls(value: string | undefined, fallback: string[]): string[] {
	const urls = value
		?.split(',')
		.map((item) => item.trim())
		.filter(Boolean);

	return urls?.length ? urls : fallback;
}

export const crawlerApiBaseUrls = splitUrls(env.CRAWLER_API_BASE_URL, [
	'http://localhost:8041',
	'http://localhost:8040',
	'http://localhost:8000'
]);
