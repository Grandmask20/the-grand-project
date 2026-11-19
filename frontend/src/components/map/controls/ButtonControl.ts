import type { IControl } from "maplibre-gl";

/** A one-button map control (Fit, 3D), in MapLibre's control look. */
export class ButtonControl implements IControl {
	private el: HTMLDivElement | null = null;
	private button: HTMLButtonElement | null = null;

	constructor(
		private readonly text: string,
		private readonly title: string,
		private onClick: () => void,
	) {}

	onAdd(): HTMLElement {
		const el = document.createElement("div");
		el.className = "maplibregl-ctrl maplibregl-ctrl-group";
		const b = document.createElement("button");
		b.type = "button";
		b.className = "grand-ctrl";
		b.title = this.title;
		b.setAttribute("aria-label", this.title);
		b.textContent = this.text;
		b.onclick = () => this.onClick();
		el.appendChild(b);
		this.el = el;
		this.button = b;
		return el;
	}

	onRemove(): void {
		this.el?.remove();
		this.el = null;
	}

	/** What a click does (the latest handler: the control is made once). */
	setOnClick(onClick: () => void): void {
		this.onClick = onClick;
	}

	setOn(on: boolean): void {
		this.button?.classList.toggle("on", on);
	}
}
