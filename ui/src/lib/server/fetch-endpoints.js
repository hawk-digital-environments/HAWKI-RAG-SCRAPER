/**
 * @param {string[]} endpoints
 * @param {typeof fetch} serverFetch
 * @param {string} pathname
 * @param {RequestInit} [init]
 */
export async function fetchEndpoints(endpoints, serverFetch, pathname, init) {
	const errors = [];
	const method = (init?.method ?? 'GET').toUpperCase();
	const candidates = ['GET', 'HEAD'].includes(method) ? endpoints : endpoints.slice(0, 1);
	const normalizedPath = pathname.startsWith('/') ? pathname : `/${pathname}`;
	for (const baseUrl of candidates) {
		const url = `${baseUrl.replace(/\/$/, '')}${normalizedPath}`;
		try {
			return { response: await serverFetch(url, init), url };
		} catch (error) {
			errors.push(`${url}: ${error}`);
		}
	}
	throw new Error(errors.join('; ') || 'No crawler API endpoints configured');
}
