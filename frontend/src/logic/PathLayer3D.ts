import {
	type CustomLayerInterface,
	type CustomRenderMethodInput,
	type Map as MapLibreMap,
	MercatorCoordinate,
} from "maplibre-gl";

/** A path piece of the 3D view: its points (lng, lat), colour and replay step. */
export interface Path3D {
	/** The path's id (the app's path index). */
	id: number;
	pts: [number, number][];
	colour: [number, number, number];
	step: number;
}

const PICK_PX = 6; // css px round the mouse a path click looks

const VS = `
attribute vec2 a_a;
attribute vec2 a_b;
attribute vec4 a_info; // side (-1 / 1), distance along (atlas units), step, path id
attribute vec3 a_col;
uniform mat4 u_m;
uniform float u_k;
uniform vec2 u_view;
uniform float u_width;
uniform float u_lift; // atlas units above the ground
uniform float u_taper; // width share left at the far limit
uniform float u_solidpx; // dashes under this many px drawn as a line
uniform float u_far; // clip w beyond which paths aren't drawn
uniform float u_near; // the view centre's clip w
uniform float u_ppuw; // screen px per atlas unit, times clip w (px per unit here = u_ppuw / w)
uniform vec2 u_dashv;
varying float v_dist;
varying float v_solid;
varying float v_step;
varying vec3 v_col;
varying float v_fade;
varying float v_id;
void main() {
	vec4 ca = u_m * vec4(a_a, u_lift * u_k, 1.0);
	vec4 cb = u_m * vec4(a_b, u_lift * u_k, 1.0);
	// behind the camera, or far off (far paths were a tangle of lines: user)
	if (ca.w <= 0.0 || ca.w > u_far) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
	vec2 pa = ca.xy / ca.w * u_view * 0.5;
	vec2 pb = (cb.w > 0.0 ? cb.xy / cb.w : ca.xy / ca.w + (ca.xy / ca.w - cb.xy / cb.w)) * u_view * 0.5;
	vec2 d = pb - pa;
	vec2 n = length(d) > 0.0001 ? normalize(vec2(-d.y, d.x)) : vec2(0.0, 1.0);
	// a ribbon of one width on screen at any distance (a line on the ground thinned to nothing far away: user)
	// thinner and fainter with distance past the view's centre (far off they were a bright tangle: user)
	float far = clamp((ca.w - u_near) / max(u_far - u_near, 0.0001), 0.0, 1.0);
	v_fade = 1.0 - far;
	vec2 px = pa + n * a_info.x * u_width * mix(1.0, u_taper, far) * 0.5;
	v_id = a_info.w;
	gl_Position = vec4(px / (u_view * 0.5) * ca.w, ca.z, ca.w);
	v_dist = a_info.y;
	// dashes smaller than a few px on screen are drawn as a line, as the old window did zoomed out (they turned into
	// a dotted blur: user)
	v_solid = (u_dashv.x + u_dashv.y) * u_ppuw / ca.w < u_solidpx ? 1.0 : 0.0;
	v_step = a_info.z;
	v_col = a_col;
}`;

const FS = `
precision mediump float;
uniform float u_pos;
uniform vec2 u_dash; // atlas units on, off (0 off: solid)
varying float v_dist;
varying float v_step;
varying vec3 v_col;
varying float v_solid;
varying float v_fade;
varying float v_id;
uniform float u_pick;
void main() {
	if (v_step >= u_pos) discard;
	if (u_dash.y > 0.0 && v_solid < 0.5 && mod(v_dist, u_dash.x + u_dash.y) > u_dash.x) discard;
	if (u_pick > 0.5) {
		float id = v_id + 1.0;
		gl_FragColor = vec4(mod(id, 256.0) / 255.0, mod(floor(id / 256.0), 256.0) / 255.0, floor(id / 65536.0) / 255.0, 1.0);
		return;
	}
	gl_FragColor = vec4(v_col * v_fade, v_fade); // premultiplied
}`;

/**
 * The 3D view's paths as a WebGL layer: a ribbon of one width on screen, just above the ground, dashes kept in their
 * shape along the path, hidden behind 3D models (MapLibre's line layer lies in the ground and vanished far away).
 */
export class PathLayer3D implements CustomLayerInterface {
	readonly id = "paths-3d-gl";
	readonly type = "custom" as const;
	readonly renderingMode = "3d" as const;
	private map: MapLibreMap | null = null;
	private gl: WebGLRenderingContext | null = null;
	private prog: WebGLProgram | null = null;
	private buf: WebGLBuffer | null = null;
	private count = 0;
	private pending: Path3D[] = [];
	private dirty = false;
	pos = 1e9;
	/** The View tab's 3D settings (STYLE_DEFAULT d3_*): height, reach (times the centre's distance), far width share,
	 * dash-to-line px. */
	lift = 3;
	far = 2.2;
	taper = 0.35;
	solidPx = 9;
	private pickReq: { x: number; y: number; done: (id: number | null) => void } | null = null;

	/**
	 * The path drawn nearest screen (x, y) css px (within PICK_PX), or null: the paths' ids are drawn into the frame's
	 * own pixels round the mouse, against its depth, and read back (clicks on the flat map missed in 3D: user).
	 */
	pickAt(x: number, y: number): Promise<number | null> {
		return new Promise((done) => {
			if (!this.map || !this.count) return done(null);
			this.pickReq = { x, y, done };
			this.map.triggerRepaint();
		});
	}
	width = 3; // css px
	dash: [number, number] = [0, 0];

	constructor(private readonly k: number) {}

	onAdd(map: MapLibreMap, gl: WebGLRenderingContext | WebGL2RenderingContext): void {
		this.map = map;
		this.gl = gl;
		const sh = (type: number, src: string) => {
			const s = gl.createShader(type) as WebGLShader;
			gl.shaderSource(s, src);
			gl.compileShader(s);
			if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(s));
			return s;
		};
		const p = gl.createProgram() as WebGLProgram;
		gl.attachShader(p, sh(gl.VERTEX_SHADER, VS));
		gl.attachShader(p, sh(gl.FRAGMENT_SHADER, FS));
		gl.linkProgram(p);
		this.prog = p;
		this.buf = gl.createBuffer();
	}

	onRemove(): void {
		if (this.gl) {
			if (this.prog) this.gl.deleteProgram(this.prog);
			if (this.buf) this.gl.deleteBuffer(this.buf);
		}
		this.map = null;
		this.gl = null;
	}

	setPaths(paths: Path3D[]): void {
		this.pending = paths;
		this.dirty = true;
		this.map?.triggerRepaint();
	}

	private upload(): void {
		const gl = this.gl;
		if (!gl || !this.buf) return;
		const out: number[] = [];
		for (const path of this.pending) {
			const m = path.pts.map(([lng, lat]) => MercatorCoordinate.fromLngLat([lng, lat]));
			let dist = 0;
			for (let i = 0; i + 1 < m.length; i++) {
				const a = m[i];
				const b = m[i + 1];
				const len = Math.hypot(b.x - a.x, b.y - a.y) / this.k;
				const [r, g, bl] = path.colour;
				// two triangles: (a, -1) (a, 1) (b, -1) / (b, -1) (a, 1) (b, 1); each end's "other end" for its direction
				const v = (p: MercatorCoordinate, q: MercatorCoordinate, side: number, d: number, flip: boolean) =>
					out.push(p.x, p.y, q.x, q.y, flip ? -side : side, d, path.step, path.id, r, g, bl);
				v(a, b, -1, dist, false);
				v(a, b, 1, dist, false);
				v(b, a, -1, dist + len, true);
				v(b, a, -1, dist + len, true);
				v(a, b, 1, dist, false);
				v(b, a, 1, dist + len, true);
				dist += len;
			}
		}
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(out), gl.STATIC_DRAW);
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
		this.count = out.length / 11;
		this.dirty = false;
	}

	private pickPass(gl: WebGLRenderingContext | WebGL2RenderingContext, p: WebGLProgram): void {
		const req = this.pickReq;
		this.pickReq = null;
		const map = this.map;
		if (!req) return;
		if (!map) {
			req.done(null);
			return;
		}
		const H = gl.drawingBufferHeight;
		const ratio = gl.drawingBufferWidth / map.getCanvas().clientWidth;
		const r = Math.max(1, Math.round(PICK_PX * ratio));
		const cx = Math.round(req.x * ratio);
		const cy = Math.round(H - req.y * ratio);
		const x0 = Math.max(0, cx - r);
		const y0 = Math.max(0, cy - r);
		const n = 2 * r + 1;
		const scissor = gl.isEnabled(gl.SCISSOR_TEST);
		const box = gl.getParameter(gl.SCISSOR_BOX) as Int32Array;
		const clear = gl.getParameter(gl.COLOR_CLEAR_VALUE) as Float32Array;
		gl.enable(gl.SCISSOR_TEST);
		gl.scissor(x0, y0, n, n);
		gl.clearColor(0, 0, 0, 0);
		gl.clear(gl.COLOR_BUFFER_BIT);
		gl.uniform1f(gl.getUniformLocation(p, "u_pick"), 1);
		gl.depthMask(false);
		gl.disable(gl.BLEND);
		gl.drawArrays(gl.TRIANGLES, 0, this.count);
		const px = new Uint8Array(n * n * 4);
		gl.readPixels(x0, y0, n, n, gl.RGBA, gl.UNSIGNED_BYTE, px);
		if (!scissor) gl.disable(gl.SCISSOR_TEST);
		gl.scissor(box[0], box[1], box[2], box[3]);
		gl.clearColor(clear[0], clear[1], clear[2], clear[3]);
		gl.uniform1f(gl.getUniformLocation(p, "u_pick"), 0);
		let best: number | null = null;
		let bestD = Number.POSITIVE_INFINITY;
		for (let j = 0; j < n; j++)
			for (let i = 0; i < n; i++) {
				const k = 4 * (j * n + i);
				const id = px[k] + px[k + 1] * 256 + px[k + 2] * 65536 - 1;
				const d = (x0 + i - cx) ** 2 + (y0 + j - cy) ** 2;
				if (id >= 0 && d < bestD) {
					bestD = d;
					best = id;
				}
			}
		req.done(best);
		map.triggerRepaint();
	}

	render(gl: WebGLRenderingContext | WebGL2RenderingContext, options: CustomRenderMethodInput): void {
		if (!this.prog || !this.map) return;
		if (this.dirty) this.upload();
		if (!this.count) return;
		const p = this.prog;
		// biome-ignore lint/correctness/useHookAtTopLevel: WebGL's useProgram, not a React hook
		gl.useProgram(p);
		gl.uniformMatrix4fv(
			gl.getUniformLocation(p, "u_m"),
			false,
			options.defaultProjectionData.mainMatrix as Float32Array,
		);
		gl.uniform1f(gl.getUniformLocation(p, "u_k"), this.k);
		gl.uniform2f(gl.getUniformLocation(p, "u_view"), gl.drawingBufferWidth, gl.drawingBufferHeight);
		const ratio = gl.drawingBufferWidth / this.map.getCanvas().clientWidth;
		gl.uniform1f(gl.getUniformLocation(p, "u_width"), this.width * ratio);
		gl.uniform1f(gl.getUniformLocation(p, "u_pos"), this.pos);
		const c = MercatorCoordinate.fromLngLat(this.map.getCenter());
		const M = options.defaultProjectionData.mainMatrix as Float32Array;
		const cw0 = M[3] * c.x + M[7] * c.y + M[15];
		gl.uniform1f(gl.getUniformLocation(p, "u_far"), this.far * cw0);
		gl.uniform1f(gl.getUniformLocation(p, "u_lift"), this.lift);
		gl.uniform1f(gl.getUniformLocation(p, "u_taper"), this.taper);
		gl.uniform1f(gl.getUniformLocation(p, "u_solidpx"), this.solidPx * ratio);
		gl.uniform1f(gl.getUniformLocation(p, "u_near"), cw0);
		gl.uniform2f(gl.getUniformLocation(p, "u_dash"), this.dash[0], this.dash[1]);
		gl.uniform2f(gl.getUniformLocation(p, "u_dashv"), this.dash[0], this.dash[1]);
		const cw = M[3] * c.x + M[7] * c.y + M[15];
		gl.uniform1f(gl.getUniformLocation(p, "u_ppuw"), this.k * 512 * 2 ** this.map.getZoom() * ratio * cw);
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		const names: [string, number, number][] = [
			["a_a", 2, 0],
			["a_b", 2, 2],
			["a_info", 4, 4],
			["a_col", 3, 8],
		];
		for (const [name, size, off] of names) {
			const loc = gl.getAttribLocation(p, name);
			gl.enableVertexAttribArray(loc);
			gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 44, off * 4);
		}
		gl.enable(gl.DEPTH_TEST);
		gl.depthFunc(gl.LEQUAL);
		gl.depthMask(true);
		gl.uniform1f(gl.getUniformLocation(p, "u_pick"), 0);
		if (this.pickReq) this.pickPass(gl, p);
		gl.depthMask(false); // faded far parts must not hide what lies behind them
		gl.enable(gl.BLEND);
		gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
		gl.drawArrays(gl.TRIANGLES, 0, this.count);
		gl.depthMask(true);
		for (const [name] of names) gl.disableVertexAttribArray(gl.getAttribLocation(p, name));
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
	}
}
