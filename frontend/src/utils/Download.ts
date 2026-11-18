/** Save data as a file in the browser's downloads. */
export function download(data: Blob | string, name: string, type = "text/plain"): void {
	const blob = typeof data === "string" ? new Blob([data], { type }) : data;
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = name;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
}
