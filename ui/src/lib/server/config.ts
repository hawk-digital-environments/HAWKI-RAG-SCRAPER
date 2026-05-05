import { env } from '$env/dynamic/private';

function splitUrls(value: string | undefined, fallback: string[]): string[] {
	const urls = value
		?.split(',')
		.map((item) => item.trim())
		.filter(Boolean);

	return urls?.length ? urls : fallback;
}

export const crawlerApiBaseUrls = splitUrls(env.CRAWLER_API_BASE_URL, [
	'http://localhost:8040',
	'http://localhost:8000'
]);

export const rabbitMqMgmtApiUrl = env.RABBITMQ_MGMT_API_URL ?? 'http://localhost:15672/api';
export const rabbitMqMgmtUser = env.RABBITMQ_MGMT_USER ?? 'guest';
export const rabbitMqMgmtPassword = env.RABBITMQ_MGMT_PASSWORD ?? 'guest';
