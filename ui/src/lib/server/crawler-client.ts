import { crawlerApiBaseUrls } from './config';

type ServerFetch = typeof fetch;

export async function fetchCrawler(
	serverFetch: ServerFetch,
	pathname: string,
	init?: RequestInit
): Promise<{ response: Response; url: string }> {
	const errors: string[] = [];
	const normalizedPath = pathname.startsWith('/') ? pathname : `/${pathname}`;

	for (const baseUrl of crawlerApiBaseUrls) {
		const url = `${baseUrl.replace(/\/$/, '')}${normalizedPath}`;
		try {
			const response = await serverFetch(url, init);
			return { response, url };
		} catch (error) {
			errors.push(`${url}: ${error}`);
		}
	}

	throw new Error(errors.join('; ') || 'No crawler API endpoints configured');
}
