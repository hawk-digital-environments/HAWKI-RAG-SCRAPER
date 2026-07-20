export type DurationUnit = 'h' | 'd' | 'w' | 'm';

export const DURATION_UNITS: { value: DurationUnit; label: string }[] = [
	{ value: 'h', label: 'Hours' },
	{ value: 'd', label: 'Days' },
	{ value: 'w', label: 'Weeks' },
	{ value: 'm', label: 'Months' }
];

export interface ParsedDuration {
	amount: number;
	unit: DurationUnit;
}

/** Parse a duration string like "24h", "7d", "3w", "2m" */
export function parseDuration(value: string): ParsedDuration | null {
	const match = value.trim().match(/^(\d+)([hdwm])$/);
	if (!match) return null;
	return { amount: parseInt(match[1], 10), unit: match[2] as DurationUnit };
}

/** Serialize a ParsedDuration back to a string like "24h" */
export function formatDuration(parsed: ParsedDuration): string {
	return `${parsed.amount}${parsed.unit}`;
}

export function isValidDuration(value: string): boolean {
	return parseDuration(value) !== null;
}
