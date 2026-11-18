import {
	type CustomLayerInterface,
	type CustomRenderMethodInput,
	type Map as MapLibreMap,
	MercatorCoordinate,
} from "maplibre-gl";

/** A path piece of the 3D view: its points (lng, lat), colour and replay step. */
export interface Path3D {
	pts: [number, number][];
	colour: [number, number, number];
	step: number;
}

const LIFT = 3; // atlas units above the ground: clear of the ground picture, under the map node pillars' caps

const VS = `
attribute vec2 a_a;
attribute vec2 a_b;
attribute vec4 a_info; // side (-1 / 1), distance along (atlas units), step, unused
attribute vec3 a_col;
uniform mat4 u_m;
uniform float u_k;
uniform vec2 u_view;
uniform float u_width;
varying float v_dist;
varying float v_step;
varying vec3 v_col;
void main() {
	vec4 ca = u_m * vec4(a_a, ${LIFT.toFixed(1)} * u_k, 1.0);
	vec4 cb = u_m * vec4(a_b, ${LIFT.toFixed(1)} * u_k, 1.0);
	if (ca.w <= 0.0) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; } // behind the camera
	vec2 pa = ca.xy / ca.w * u_view * 0.5;
	vec2 pb = (cb.w > 0.0 ? cb.xy / cb.w : ca.xy / ca.w + (ca.xy / ca.w - cb.xy / cb.w)) * u_view * 0.5;
	vec2 d = pb - pa;
	vec2 n = length(d) > 0.0001 ? normalize(vec2(-d.y, d.x)) : vec2(0.0, 1.0);
	// a ribbon of one width on screen at any distance (a line on the ground thinned to nothing far away: user)
	vec2 px = pa + n * a_info.x * u_width * 0.5;
	gl_Position = vec4(px / (u_view * 0.5) * ca.w, ca.z, ca.w);
	v_dist = a_info.y;
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
void main() {
	if (v_step >= u_pos) discard;
	if (u_dash.y > 0.0 && mod(v_dist, u_dash.x + u_dash.y) > u_dash.x) discard;
	gl_FragColor = vec4(v_col, 1.0);
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
					out.push(p.x, p.y, q.x, q.y, flip ? -side : side, d, path.step, 0, r, g, bl);
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
		gl.uniform2f(gl.getUniformLocation(p, "u_dash"), this.dash[0], this.dash[1]);
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
		gl.disable(gl.BLEND);
		gl.drawArrays(gl.TRIANGLES, 0, this.count);
		for (const [name] of names) gl.disableVertexAttribArray(gl.getAttribLocation(p, name));
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
	}
}
