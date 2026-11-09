import { crawlerApiBaseUrls } from './config';
import { fetchEndpoints } from './fetch-endpoints.js';

type ServerFetch = typeof fetch;

export async function fetchCrawler(
	serverFetch: ServerFetch,
	pathname: string,
	init?: RequestInit
): Promise<{ response: Response; url: string }> {
	return fetchEndpoints(crawlerApiBaseUrls, serverFetch, pathname, init);
}
