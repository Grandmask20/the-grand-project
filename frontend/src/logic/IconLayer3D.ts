import {
	type CustomLayerInterface,
	type CustomRenderMethodInput,
	type Map as MapLibreMap,
	MercatorCoordinate,
} from "maplibre-gl";

/** An icon of the 3D view: its map node's place, picture, place in the row, the model height under it, replay step. */
export interface Icon3D {
	lng: number;
	lat: number;
	name: string;
	slot: number;
	lift: number;
	step: number;
}

const CELL = 64; // px per picture in the texture
const COLS = 32;
const HALF = 13; // atlas units: half an icon (an icon is 26 units across)
const ROW = 36; // atlas units between icons of a row
const BASE = 11 + HALF; // atlas units from the ground to the icon's middle

const VS = `
attribute vec2 a_xy;
attribute vec2 a_corner;
attribute vec4 a_info; // slot, lift, step, unused
attribute vec4 a_uv;
uniform mat4 u_m;
uniform float u_k;
uniform float u_models;
uniform vec2 u_view;
varying vec2 v_uv;
varying float v_step;
void main() {
	vec3 p = vec3(a_xy, (${BASE.toFixed(1)} + a_info.y * u_models) * u_k);
	vec4 c0 = u_m * vec4(p, 1.0);
	vec4 c1 = u_m * vec4(p + vec3(${HALF.toFixed(1)} * u_k, 0.0, 0.0), 1.0);
	vec2 d = (c1.xy / c1.w - c0.xy / c0.w) * u_view * 0.5;
	float hs = length(d); // screen px of half an icon at this distance (shrinks with it, as the ground does)
	vec2 off = vec2(a_corner.x + a_info.x * ${(ROW / HALF).toFixed(4)}, a_corner.y) * hs * 2.0 / u_view;
	gl_Position = vec4((c0.xy / c0.w + off) * c0.w, c0.z, c0.w);
	v_uv = mix(a_uv.xy, a_uv.zw, a_corner * 0.5 + 0.5);
	v_step = a_info.z;
}`;

const FS = `
precision mediump float;
uniform sampler2D u_tex;
uniform float u_pos;
varying vec2 v_uv;
varying float v_step;
void main() {
	if (v_step >= u_pos) discard; // the replay hasn't reached it
	vec4 c = texture2D(u_tex, v_uv);
	if (c.a < 0.35) discard; // clear edges, so the depth test hides icons behind 3D models
	gl_FragColor = c;
}`;

/**
 * The 3D view's icons as a WebGL layer of their own: real 3D places above their map node (on top of its model),
 * facing the camera, sized like the ground at their distance, and hidden behind 3D models by the depth test. MapLibre's
 * own icon layer can't do these: its icons float higher the further away they are and draw over models (user).
 */
export class IconLayer3D implements CustomLayerInterface {
	readonly id = "icons-3d-gl";
	readonly type = "custom" as const;
	readonly renderingMode = "3d" as const;
	private map: MapLibreMap | null = null;
	private gl: WebGLRenderingContext | null = null;
	private prog: WebGLProgram | null = null;
	private buf: WebGLBuffer | null = null;
	private tex: WebGLTexture | null = null;
	private count = 0;
	private names: string[] = [];
	private canvas = document.createElement("canvas");
	private pending: Icon3D[] = [];
	private dirty = false;
	models = true;
	pos = 1e9; // the replay's step (no replay: everything)
	/** Atlas units -> mercator units (scale / world). */
	constructor(
		private readonly k: number,
		private readonly picture: (name: string) => Promise<CanvasImageSource | null>,
	) {}

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
		this.tex = gl.createTexture();
	}

	onRemove(): void {
		const gl = this.gl;
		if (gl) {
			if (this.prog) gl.deleteProgram(this.prog);
			if (this.buf) gl.deleteBuffer(this.buf);
			if (this.tex) gl.deleteTexture(this.tex);
		}
		this.map = null;
		this.gl = null;
	}

	/** Give the icons to draw (pictures are fetched for names not seen yet). */
	async setIcons(icons: Icon3D[]): Promise<void> {
		const fresh = [...new Set(icons.map((i) => i.name))].filter((n) => !this.names.includes(n));
		if (fresh.length) {
			const pics = await Promise.all(fresh.map((n) => this.picture(n).catch(() => null)));
			this.names.push(...fresh);
			const rows = Math.ceil(this.names.length / COLS);
			const old = this.canvas;
			const c = document.createElement("canvas");
			c.width = COLS * CELL;
			c.height = Math.max(1, rows) * CELL;
			const ctx = c.getContext("2d");
			if (ctx) {
				if (old.width) ctx.drawImage(old, 0, 0);
				fresh.forEach((_n, j) => {
					const pic = pics[j];
					const i = this.names.length - fresh.length + j;
					if (pic) ctx.drawImage(pic, (i % COLS) * CELL, Math.floor(i / COLS) * CELL, CELL, CELL);
				});
			}
			this.canvas = c;
		}
		this.pending = icons;
		this.dirty = true;
		this.map?.triggerRepaint();
	}

	private upload(): void {
		const gl = this.gl;
		if (!gl || !this.buf || !this.tex) return;
		const H = this.canvas.height;
		const W = this.canvas.width;
		const data = new Float32Array(this.pending.length * 6 * 12);
		let o = 0;
		const corners = [
			[-1, -1],
			[1, -1],
			[1, 1],
			[-1, -1],
			[1, 1],
			[-1, 1],
		];
		for (const ic of this.pending) {
			const m = MercatorCoordinate.fromLngLat([ic.lng, ic.lat]);
			const i = this.names.indexOf(ic.name);
			const u0 = ((i % COLS) * CELL) / W;
			const v0 = (Math.floor(i / COLS) * CELL) / H;
			const u1 = u0 + CELL / W;
			const v1 = v0 + CELL / H;
			for (const [cx, cy] of corners) {
				// y grows down the picture, up the screen: the top corners (cy = 1) take the picture's top (v0)
				data.set([m.x, m.y, cx, cy, ic.slot, ic.lift, ic.step, 0, u0, v1, u1, v0], o);
				o += 12;
			}
		}
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
		this.count = this.pending.length * 6;
		gl.bindTexture(gl.TEXTURE_2D, this.tex);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.canvas);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
		this.dirty = false;
	}

	render(gl: WebGLRenderingContext | WebGL2RenderingContext, options: CustomRenderMethodInput): void {
		if (!this.prog) return;
		if (this.dirty) this.upload();
		if (!this.count) return;
		const p = this.prog;
		// biome-ignore lint/correctness/useHookAtTopLevel: WebGL's useProgram, not a React hook
		gl.useProgram(p);
		// mercator 0..1 -> clip space (modelViewProjectionMatrix here is for world px, not mercator)
		gl.uniformMatrix4fv(gl.getUniformLocation(p, "u_m"), false, options.defaultProjectionData.mainMatrix as Float32Array);
		gl.uniform1f(gl.getUniformLocation(p, "u_k"), this.k);
		gl.uniform1f(gl.getUniformLocation(p, "u_models"), this.models ? 1 : 0);
		gl.uniform1f(gl.getUniformLocation(p, "u_pos"), this.pos);
		gl.uniform2f(gl.getUniformLocation(p, "u_view"), gl.drawingBufferWidth, gl.drawingBufferHeight);
		gl.activeTexture(gl.TEXTURE0);
		gl.bindTexture(gl.TEXTURE_2D, this.tex);
		gl.uniform1i(gl.getUniformLocation(p, "u_tex"), 0);
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		const attr = (name: string, size: number, offset: number) => {
			const loc = gl.getAttribLocation(p, name);
			gl.enableVertexAttribArray(loc);
			gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 48, offset * 4);
		};
		attr("a_xy", 2, 0);
		attr("a_corner", 2, 2);
		attr("a_info", 4, 4);
		attr("a_uv", 4, 8);
		gl.enable(gl.DEPTH_TEST);
		gl.depthFunc(gl.LEQUAL);
		gl.depthMask(true);
		gl.enable(gl.BLEND);
		gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
		gl.drawArrays(gl.TRIANGLES, 0, this.count);
	}
}
