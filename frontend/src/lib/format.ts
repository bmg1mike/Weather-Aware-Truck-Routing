export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** Retry hints in units a driver reads at a glance: 60 -> "60 seconds", 37632 -> "10 hours". */
export function formatWait(seconds: number): string {
  if (seconds < 120) return `${seconds} seconds`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} minutes`;
  const hours = Math.round(seconds / 3600);
  return hours === 1 ? '1 hour' : `${hours} hours`;
}
