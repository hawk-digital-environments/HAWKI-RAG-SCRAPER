import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

import {
	rabbitMqMgmtApiUrl,
	rabbitMqMgmtPassword,
	rabbitMqMgmtUser
} from '$lib/server/config';

type RabbitMqQueuePayload = {
	name?: unknown;
	vhost?: unknown;
	state?: unknown;
	messages?: unknown;
	messages_ready?: unknown;
	messages_unacknowledged?: unknown;
	consumers?: unknown;
};

export const GET: RequestHandler = async ({ fetch }) => {
	const auth = btoa(`${rabbitMqMgmtUser}:${rabbitMqMgmtPassword}`);

	try {
		const response = await fetch(`${rabbitMqMgmtApiUrl}/queues`, {
			headers: {
				authorization: `Basic ${auth}`
			}
		});
		const text = await response.text();
		if (!response.ok) {
			return json(
				{
					error: 'RabbitMQ management API request failed',
					status: response.status,
					body: text
				},
				{ status: response.status }
			);
		}

		let payload: unknown = [];
		try {
			payload = JSON.parse(text);
		} catch {
			payload = [];
		}

		const queues = Array.isArray(payload)
			? payload.map((item: RabbitMqQueuePayload) => ({
					name: typeof item?.name === 'string' ? item.name : 'unknown',
					vhost: typeof item?.vhost === 'string' ? item.vhost : '/',
					state: typeof item?.state === 'string' ? item.state : 'unknown',
					messages: typeof item?.messages === 'number' ? item.messages : 0,
					messages_ready: typeof item?.messages_ready === 'number' ? item.messages_ready : 0,
					messages_unacknowledged:
						typeof item?.messages_unacknowledged === 'number'
							? item.messages_unacknowledged
							: 0,
					consumers: typeof item?.consumers === 'number' ? item.consumers : 0
				}))
			: [];

		return json({ queues }, { status: 200 });
	} catch (error) {
		return json(
			{
				error: `RabbitMQ management unavailable at ${rabbitMqMgmtApiUrl}/queues: ${error}`
			},
			{ status: 502 }
		);
	}
};
