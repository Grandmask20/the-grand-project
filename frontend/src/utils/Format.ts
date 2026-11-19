/** "1 map", "3 maps". */
export function plural(n: number, word: string, many = `${word}s`): string {
	return `${n} ${n === 1 ? word : many}`;
}

/** A file's name from its path (either slash). */
export function baseName(path: string): string {
	return path.split(/[\\/]/).pop() ?? path;
}

/** Seconds as "1:05" / "12 s". */
export function duration(s: number): string {
	const t = Math.round(s); // rounded first: 119.6 s is 2:00, not 1:60 (CodeRabbit)
	if (t < 60) return `${t} s`;
	return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

/** Bytes as "1.2 MB". */
export function size(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
	return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}
