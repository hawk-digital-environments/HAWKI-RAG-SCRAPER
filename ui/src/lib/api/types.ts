export type Protocol = 'https' | 'http';
export type ConflictSource = 'sitemap' | 'page';
export type JobStatus = 'running' | 'paused' | 'stopping' | 'completed' | 'failed' | 'cancelled';

export interface ConflictResolution {
	last_modified: ConflictSource;
	language: ConflictSource;
}

export interface HostEntrypoint {
	type: 'host';
	src: string;
	protocol?: Protocol;
}

export interface SitemapEntrypoint {
	type: 'sitemap';
	src: string;
	conflict_resolution?: ConflictResolution;
}

export type Entrypoint = HostEntrypoint | SitemapEntrypoint;

export interface Profile {
	id: string;
	name: string;
	readonlyExample?: boolean;
	entrypoints: Entrypoint[];
	discovery?: { hosts?: string[] };
	forbidden?: { hosts?: string[]; url_patterns?: string[] };
	content?: {
		content_selectors?: string[];
		noise_phrases?: string[];
		noise_patterns?: string[];
		tag_selectors?: string[];
	};
	max_execution_time: string;
	max_storage_time: string;
	rescrape_failed: boolean;
	max_concurrency?: number;
	max_rpm?: number;
	skip_images?: boolean;
	max_images_per_page?: number;
	max_pages?: number;
	max_link_density?: number;
	discovery_mode?: boolean;
}

export type ProfileInput = Omit<Profile, 'id'>;

export interface Task {
	id: string;
	name: string;
	profileId: string;
	schedule?: string;
}

export type TaskInput = Omit<Task, 'id'>;

export interface Job {
	id: string;
	taskId: string;
	profileId: string;
	status: JobStatus;
	startTime: string;
	endTime?: string;
	log: string[];
	failedPages?: string[];
	dataExpired?: boolean;
}

export interface Queue {
	name: string;
	vhost?: string;
	ready: number;
	unacked: number;
	total: number;
}
