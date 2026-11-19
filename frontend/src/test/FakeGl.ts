/**
 * A WebGL context that does nothing (jsdom has none): every call is recorded, objects are plain {}, shaders always
 * compile and link, constants are numbers. Enough to run the 3D view's layers (onAdd, data upload, render, pick) and
 * check what they asked of the GPU.
 */
export function fakeGl() {
	const calls: { name: string; args: unknown[] }[] = [];
	let n = 0;
	let drawn = [0, 0, 0, 0]; // what every pixel read back holds (pick colours)
	const fns: Record<string, (...a: unknown[]) => unknown> = {
		getShaderParameter: () => true,
		getProgramParameter: () => true,
		getShaderInfoLog: () => "",
		getProgramInfoLog: () => "",
		getAttribLocation: () => 0,
		getUniformLocation: () => ({}),
		getExtension: () =>
			new Proxy({}, { get: (_t, k) => (typeof k === "string" && /^[A-Z_0-9]+$/.test(k) ? 1 : () => ({})) }),
		getParameter: () => 0,
		checkFramebufferStatus: () => 36053, // FRAMEBUFFER_COMPLETE
		isContextLost: () => false,
		getError: () => 0,
		readPixels: (...a: unknown[]) => {
			const out = a[6] as Uint8Array | undefined;
			if (out) for (let k = 0; k < out.length; k += 4) out.set(drawn, k);
		},
	};
	const gl = new Proxy(
		{ canvas: document.createElement("canvas"), drawingBufferWidth: 1000, drawingBufferHeight: 800 } as Record<
			string,
			unknown
		>,
		{
			get(target, key) {
				if (typeof key !== "string") return undefined;
				if (key in target) return target[key];
				if (/^[A-Z_0-9]+$/.test(key)) return ++n; // a constant
				return (...args: unknown[]) => {
					calls.push({ name: key, args });
					if (key in fns) return fns[key](...args);
					if (key.startsWith("create")) return {};
					return undefined;
				};
			},
		},
	);
	return {
		gl: gl as unknown as WebGLRenderingContext,
		calls,
		called: (name: string) => calls.filter((c) => c.name === name),
		/** Every pixel read back from now on holds this pick code, as the layers draw it (3 bytes and an opaque
		 * alpha; 0: nothing drawn). */
		draws: (code: number) => {
			drawn = code ? [code % 256, Math.floor(code / 256) % 256, Math.floor(code / 65536), 255] : [0, 0, 0, 0];
		},
	};
}

/** Whether a promise has settled yet (after the microtasks queued so far). */
export async function settled(p: Promise<unknown>): Promise<boolean> {
	let done = false;
	void p.then(
		() => {
			done = true;
		},
		() => {
			done = true;
		},
	);
	await Promise.resolve();
	await Promise.resolve();
	return done;
}
