import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

import {
	rabbitMqMgmtApiUrl,
	rabbitMqMgmtPassword,
	rabbitMqMgmtUser
} from '$lib/server/config';

type PurgeRequest = {
	name?: unknown;
	vhost?: unknown;
};

export const POST: RequestHandler = async ({ fetch, request }) => {
	let payload: PurgeRequest = {};
	try {
		payload = await request.json();
	} catch {
		return json({ error: 'Request body must be JSON' }, { status: 400 });
	}

	const name = typeof payload.name === 'string' ? payload.name : '';
	const vhost = typeof payload.vhost === 'string' && payload.vhost ? payload.vhost : '/';
	if (!name) {
		return json({ error: 'Queue name is required' }, { status: 400 });
	}

	const auth = btoa(`${rabbitMqMgmtUser}:${rabbitMqMgmtPassword}`);
	const endpoint = `${rabbitMqMgmtApiUrl}/queues/${encodeURIComponent(vhost)}/${encodeURIComponent(name)}/contents`;

	try {
		const response = await fetch(endpoint, {
			method: 'DELETE',
			headers: {
				authorization: `Basic ${auth}`
			}
		});
		const text = await response.text();
		if (!response.ok) {
			return json(
				{
					error: 'RabbitMQ purge request failed',
					status: response.status,
					body: text
				},
				{ status: response.status }
			);
		}

		return json({ ok: true }, { status: 200 });
	} catch (error) {
		return json(
			{
				error: `RabbitMQ management unavailable at ${endpoint}: ${error}`
			},
			{ status: 502 }
		);
	}
};
