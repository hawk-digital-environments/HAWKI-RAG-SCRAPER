import fs from 'node:fs/promises';
import path from 'node:path';

import { env } from '$env/dynamic/private';
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

type StoredTask = {
	id: string;
	name?: string;
	profileId?: string;
	schedule?: string;
	deleted?: boolean;
};

const tasksHostFile = env.TASKS_HOST_FILE ?? path.resolve(process.cwd(), '..', 'tasks', 'tasks.json');

function slug(value: string): string {
	return value
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9._-]+/g, '-')
		.replace(/^-+|-+$/g, '') || 'task';
}

async function readTasks(): Promise<StoredTask[]> {
	try {
		const text = await fs.readFile(tasksHostFile, 'utf-8');
		const parsed: unknown = JSON.parse(text);
		return Array.isArray(parsed)
			? parsed.filter((task): task is StoredTask => {
					return (
						!!task &&
						typeof task === 'object' &&
						typeof (task as StoredTask).id === 'string' &&
						(
							(task as StoredTask).deleted === true ||
							(
								typeof (task as StoredTask).name === 'string' &&
								typeof (task as StoredTask).profileId === 'string'
							)
						)
					);
				})
			: [];
	} catch (error) {
		if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') {
			return [];
		}
		throw error;
	}
}

async function writeTasks(tasks: StoredTask[]): Promise<void> {
	await fs.mkdir(path.dirname(tasksHostFile), { recursive: true });
	await fs.writeFile(tasksHostFile, `${JSON.stringify(tasks, null, 2)}\n`, 'utf-8');
}

function normalizeTask(input: unknown, fallbackId: string): StoredTask | undefined {
	if (!input || typeof input !== 'object') return undefined;
	const candidate = input as Record<string, unknown>;
	const name = typeof candidate.name === 'string' ? candidate.name.trim() : '';
	const profileId = typeof candidate.profileId === 'string' ? candidate.profileId.trim() : '';
	const schedule = typeof candidate.schedule === 'string' && candidate.schedule.trim()
		? candidate.schedule.trim()
		: undefined;
	if (!name || !profileId) return undefined;
	return {
		id: typeof candidate.id === 'string' && candidate.id.trim() ? candidate.id.trim() : fallbackId,
		name,
		profileId,
		schedule
	};
}

export const GET: RequestHandler = async () => {
	const tasks = await readTasks();
	return json({
		tasks: tasks.filter((task) => task.deleted !== true),
		deletedTaskIds: tasks.filter((task) => task.deleted === true).map((task) => task.id)
	});
};

export const POST: RequestHandler = async ({ request }) => {
	let body: unknown;
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const fallbackId = `${slug((body as Record<string, unknown>)?.profileId as string)}-${Date.now()}`;
	const task = normalizeTask(body, fallbackId);
	if (!task) {
		return json({ error: 'Task must include name and profileId' }, { status: 400 });
	}

	const tasks = await readTasks();
	const nextTasks = [...tasks.filter((item) => item.id !== task.id), task];
	await writeTasks(nextTasks);
	return json(task, { status: 201 });
};
