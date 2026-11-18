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
	/** Its map node's atlas point. */
	atlas: [number, number];
	/** The icon's id (the app's icon index). */
	id: number;
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
attribute vec4 a_info; // slot, lift, step, icon id
attribute vec4 a_uv;
uniform mat4 u_m;
uniform float u_k;
uniform float u_models;
uniform vec2 u_view;
uniform float u_size;
uniform float u_sel;
uniform float u_far; // clip w beyond which icons aren't drawn (a render distance: user)
varying vec2 v_uv;
varying vec2 v_local;
varying float v_id;
varying float v_sel;
varying float v_step;
void main() {
	vec3 p = vec3(a_xy, (${BASE.toFixed(1)} + a_info.y * u_models) * u_k);
	vec4 c0 = u_m * vec4(p, 1.0);
	if (c0.w > u_far) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
	// screen px of half an icon at this distance: in perspective sizes go as 1 / w, so the size at the view's centre
	// (u_size, with its w) scaled by w (measuring along one map direction changed as the map turned: user)
	float hs = u_size / c0.w;
	// the selected icon's quad is bigger, for the ring drawn round it (the flat map's ring lay on the ground: user)
	float grow = abs(a_info.w - u_sel) < 0.5 ? 1.35 : 1.0;
	vec2 off = vec2(a_corner.x * grow + a_info.x * ${(ROW / HALF).toFixed(4)}, a_corner.y * grow) * hs * 2.0 / u_view;
	v_local = a_corner * grow;
	v_id = a_info.w;
	v_sel = grow > 1.0 ? 1.0 : 0.0;
	gl_Position = vec4((c0.xy / c0.w + off) * c0.w, c0.z, c0.w);
	v_uv = mix(a_uv.xy, a_uv.zw, a_corner * 0.5 + 0.5);
	v_step = a_info.z;
}`;

const FS = `
precision highp float;
uniform sampler2D u_tex;
uniform float u_pos;
uniform float u_pick; // 1: draw each icon's id as its colour (clicks read it back)
varying vec2 v_uv;
varying float v_step;
varying vec2 v_local;
varying float v_id;
varying float v_sel;
void main() {
	if (v_step >= u_pos) discard; // the replay hasn't reached it
	float r = length(v_local);
	if (v_sel > 0.5 && r > 1.05) {
		if (r > 1.32 || u_pick > 0.5) discard;
		gl_FragColor = vec4(1.0, 0.9, 0.35, 1.0); // the selection ring
		return;
	}
	if (abs(v_local.x) > 1.0 || abs(v_local.y) > 1.0) discard;
	vec4 c = texture2D(u_tex, v_uv);
	if (c.a < 0.35) discard; // clear edges, so the depth test hides icons behind 3D models
	if (u_pick > 0.5) {
		float id = v_id + 1.0;
		gl_FragColor = vec4(mod(id, 256.0) / 255.0, mod(floor(id / 256.0), 256.0) / 255.0, floor(id / 65536.0) / 255.0, 1.0);
		return;
	}
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
				data.set([m.x, m.y, cx, cy, ic.slot, ic.lift, ic.step, ic.id, u0, v1, u1, v0], o);
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

	/** The selected icon's id (-1: none): drawn with a ring. */
	selected = -1;
	/** Icons are drawn out to this many times the view centre's distance (View tab). */
	far = 2.6;
	/** Icons' size in 3D, and the models' height scale (View tab). */
	sizeScale = 1;
	liftScale = 1;
	private pickReq: { x: number; y: number; done: (id: number | null) => void } | null = null;

	/**
	 * The icon drawn at screen (x, y) css px, or null: the next frame draws every icon's id as its colour into a
	 * hidden picture and reads the pixel under the mouse, so what you see is what you click (user).
	 */
	pickAt(x: number, y: number): Promise<number | null> {
		return new Promise((done) => {
			if (!this.map || !this.count) return done(null);
			this.pickReq = { x, y, done };
			this.map.triggerRepaint();
		});
	}

	/** The last frame's mercator -> clip matrix and centre size (for clicks on the 3D view: pickScreen). */
	last: { M: Float32Array; size: number } | null = null;

	/**
	 * The atlas point a click at screen (x, y) css px means in the 3D view: the icon or map node pillar drawn nearest
	 * to it (within 24 px), else null. Clicks were read on the flat map under the 3D models (user).
	 */
	pickScreen(x: number, y: number, nodes: { x: number; y: number; ax: number; ay: number }[]): [number, number] | null {
		const map = this.map;
		const L = this.last;
		if (!map || !L) return null;
		const W = map.getCanvas().clientWidth;
		const H = map.getCanvas().clientHeight;
		const M = L.M;
		const proj = (mx: number, my: number, z: number): [number, number, number] | null => {
			const cw = M[3] * mx + M[7] * my + M[11] * z + M[15];
			if (cw <= 0) return null;
			const cx = (M[0] * mx + M[4] * my + M[8] * z + M[12]) / cw;
			const cy = (M[1] * mx + M[5] * my + M[9] * z + M[13]) / cw;
			return [((cx + 1) / 2) * W, ((1 - cy) / 2) * H, cw];
		};
		const ratio = map.getCanvas().width / W;
		let best: [number, number] | null = null;
		let bestD = 24;
		for (const ic of this.pending) {
			const m = MercatorCoordinate.fromLngLat([ic.lng, ic.lat]);
			const s = proj(m.x, m.y, (BASE + (this.models ? ic.lift : 0)) * this.k);
			if (!s) continue;
			const half = L.size / s[2] / ratio; // css px of half an icon there
			const sx = s[0] + ic.slot * (ROW / HALF) * half;
			const d = Math.hypot(sx - x, s[1] - y);
			if (d < Math.max(bestD, half * 1.1)) {
				bestD = d;
				// the icon's place on the flat map: its row above the node, as the app keeps it
				best = [ic.atlas[0] + ic.slot * ROW, ic.atlas[1] - 24];
			}
		}
		if (best) return best;
		for (const n of nodes) {
			const s = proj(n.x, n.y, 12 * this.k);
			if (!s) continue;
			const d = Math.hypot(s[0] - x, s[1] - y);
			if (d < bestD) {
				bestD = d;
				best = [n.ax, n.ay];
			}
		}
		return best;
	}

	render(gl: WebGLRenderingContext | WebGL2RenderingContext, options: CustomRenderMethodInput): void {
		if (!this.prog) return;
		if (this.dirty) this.upload();
		if (!this.count) return;
		const p = this.prog;
		// biome-ignore lint/correctness/useHookAtTopLevel: WebGL's useProgram, not a React hook
		gl.useProgram(p);
		// mercator 0..1 -> clip space (modelViewProjectionMatrix here is for world px, not mercator)
		gl.uniformMatrix4fv(
			gl.getUniformLocation(p, "u_m"),
			false,
			options.defaultProjectionData.mainMatrix as Float32Array,
		);
		gl.uniform1f(gl.getUniformLocation(p, "u_k"), this.k);
		gl.uniform1f(gl.getUniformLocation(p, "u_models"), this.models ? this.liftScale : 0);
		gl.uniform1f(gl.getUniformLocation(p, "u_pos"), this.pos);
		gl.uniform2f(gl.getUniformLocation(p, "u_view"), gl.drawingBufferWidth, gl.drawingBufferHeight);
		const size = this.centreSize(options.defaultProjectionData.mainMatrix as Float32Array, gl);
		this.last = { M: Float32Array.from(options.defaultProjectionData.mainMatrix as Float32Array), size };
		gl.uniform1f(gl.getUniformLocation(p, "u_size"), size * this.sizeScale);
		gl.uniform1f(gl.getUniformLocation(p, "u_far"), this.far * this.centreW());
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
		gl.uniform1f(gl.getUniformLocation(p, "u_sel"), this.selected);
		if (this.pickReq) this.pickPass(gl);
		gl.uniform1f(gl.getUniformLocation(p, "u_pick"), 0);
		gl.enable(gl.DEPTH_TEST);
		gl.depthFunc(gl.LEQUAL);
		gl.depthMask(true);
		gl.enable(gl.BLEND);
		gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
		gl.drawArrays(gl.TRIANGLES, 0, this.count);
		// leave WebGL as MapLibre expects it (left on, its next draw read our buffer: black frames, user)
		for (const name of ["a_xy", "a_corner", "a_info", "a_uv"])
			gl.disableVertexAttribArray(gl.getAttribLocation(p, name));
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
	}

	/**
	 * Answer the waiting click: draw the icons' ids into the one pixel under the mouse of the frame being drawn, tested
	 * against its depth (3D models in front hide icons behind them, as on screen), read it, and draw the frame again.
	 */
	private pickPass(gl: WebGLRenderingContext | WebGL2RenderingContext): void {
		const req = this.pickReq;
		this.pickReq = null;
		const map = this.map;
		if (!req) return;
		if (!map || !this.prog) {
			req.done(null);
			return;
		}
		const H = gl.drawingBufferHeight;
		const ratio = gl.drawingBufferWidth / map.getCanvas().clientWidth;
		const x = Math.round(req.x * ratio);
		const y = Math.round(H - req.y * ratio);
		const scissor = gl.isEnabled(gl.SCISSOR_TEST);
		const box = gl.getParameter(gl.SCISSOR_BOX) as Int32Array;
		const clear = gl.getParameter(gl.COLOR_CLEAR_VALUE) as Float32Array;
		gl.enable(gl.SCISSOR_TEST);
		gl.scissor(x, y, 1, 1);
		gl.clearColor(0, 0, 0, 0);
		gl.clear(gl.COLOR_BUFFER_BIT); // colour only: the models' depth stays
		gl.uniform1f(gl.getUniformLocation(this.prog, "u_pick"), 1);
		gl.enable(gl.DEPTH_TEST);
		gl.depthFunc(gl.LEQUAL);
		gl.depthMask(false);
		gl.disable(gl.BLEND);
		gl.drawArrays(gl.TRIANGLES, 0, this.count);
		const px = new Uint8Array(4);
		gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
		if (!scissor) gl.disable(gl.SCISSOR_TEST);
		gl.scissor(box[0], box[1], box[2], box[3]);
		gl.clearColor(clear[0], clear[1], clear[2], clear[3]);
		const id = px[0] + px[1] * 256 + px[2] * 65536 - 1;
		req.done(id >= 0 ? id : null);
		map.triggerRepaint(); // the pixel used for the answer is drawn again
	}

	/** The view centre's clip w (its distance from the camera, in the projection's terms). */
	private centreW(): number {
		const map = this.map;
		const L = this.last;
		if (!map || !L) return 1e9;
		const c = MercatorCoordinate.fromLngLat(map.getCenter());
		return L.M[3] * c.x + L.M[7] * c.y + L.M[15];
	}

	/** Half an icon in drawing px at the view's centre, times the centre's clip w (see the vertex shader). */
	private centreSize(M: Float32Array, gl: WebGLRenderingContext | WebGL2RenderingContext): number {
		const map = this.map;
		if (!map) return 0;
		const c = MercatorCoordinate.fromLngLat(map.getCenter());
		const w = M[3] * c.x + M[7] * c.y + M[15];
		// ground px per atlas unit at the centre: a mercator unit spans 512 * 2^zoom css px
		const ppu = this.k * 512 * 2 ** map.getZoom() * (gl.drawingBufferWidth / map.getCanvas().clientWidth);
		return HALF * ppu * w;
	}
}
