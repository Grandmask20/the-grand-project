import {
	type CustomLayerInterface,
	type CustomRenderMethodInput,
	type Map as MapLibreMap,
	MercatorCoordinate,
} from "maplibre-gl";

import { PickQueue, pickColour, pickPixel, readPickBox } from "./PickPass";

export { pickCode, pickItem } from "./Pick";

/** One extruded shape of the 3D view: its rings (lng, lat; outer then holes), heights in metres, colour, centre. */
export interface Model3D {
	rings: [number, number][][];
	base: number;
	height: number;
	colour: [number, number, number];
	anchor: [number, number]; // lng, lat of its structure's centre
	step: number;
	/** What a click on it selects (pickCode), 0 for nothing. */
	pick: number;
}

const VS = `
attribute vec3 a_pos; // mercator x, y; z (mercator height)
attribute vec2 a_anchor; // the structure's centre
attribute vec3 a_col;
attribute vec3 a_normal; // x, y, z (a top face: 0, 0, 1)
attribute float a_step;
attribute vec3 a_pick; // the pick code's three bytes, 0..1
uniform mat4 u_m;
uniform float u_size;
uniform float u_height;
uniform float u_far;
uniform float u_pos;
uniform float u_fogOn; // 1: models far off fade into the sky's haze (View: sky and fog)
varying vec3 v_col;
varying float v_show;
varying vec3 v_pick;
varying float v_fog;
void main() {
	v_pick = a_pick;
	vec4 ca = u_m * vec4(a_anchor, 0.0, 1.0);
	if (ca.w > u_far) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; } // past the render distance
	// the haze: none up to half the render distance, all of it at its end (so they fade out rather than pop)
	v_fog = u_fogOn * smoothstep(0.5 * u_far, u_far, ca.w);
	vec2 xy = a_anchor + (a_pos.xy - a_anchor) * u_size;
	gl_Position = u_m * vec4(xy, a_pos.z * u_size * u_height, 1.0);
	// light from the north-west and above; tops brightest, as MapLibre's own models looked
	float light = a_normal.z > 0.5 ? 1.0 : 0.62 + 0.3 * max(dot(normalize(a_normal.xy), normalize(vec2(-0.6, -0.8))), 0.0);
	v_col = a_col * light;
	// the timelapse's step compared here, in the vertex shader's full precision (a mediump fragment shader holds
	// whole numbers only to 2048: CodeRabbit)
	v_show = a_step < u_pos ? 1.0 : 0.0;
}`;

const FS = `
precision mediump float;
uniform float u_pick; // 1: draw each model's pick code as its colour (clicks read it back)
uniform vec3 u_sel; // the selected map node's pick code (bytes, 0..1); its models are lit up
uniform float u_selOn;
uniform vec3 u_fogCol;
varying vec3 v_col;
varying float v_show;
varying vec3 v_pick;
varying float v_fog;
void main() {
	if (v_show < 0.5) discard;
	if (u_pick > 0.5) { gl_FragColor = vec4(v_pick, 1.0); return; }
	// the selected map node's pillar or structure, in the selection's gold (its icons keep their look: a selected
	// map node and a selected icon looked the same with the ring on the icon: user)
	bool sel = u_selOn > 0.5 && all(lessThan(abs(v_pick - u_sel), vec3(0.002)));
	vec3 col = sel ? mix(v_col, vec3(1.0, 0.8, 0.2), 0.6) : v_col;
	gl_FragColor = vec4(mix(col, u_fogCol, v_fog), 1.0);
}`;

const STRIDE = 15; // floats per vertex

/**
 * The 3D view's models (map node pillars, towers, cities, halls, strongholds) as a WebGL layer of our own: a size
 * that scales width and height around each structure's centre, an extra height, and a render distance, all applied
 * at once by the shader (MapLibre's fill-extrusion only stretched heights and rebuilt every shape on each change:
 * user). Writes depth, so the icons and paths drawn after it hide behind models.
 */
export class ModelLayer3D implements CustomLayerInterface {
	readonly id = "models-3d-gl";
	readonly type = "custom" as const;
	readonly renderingMode = "3d" as const;
	private map: MapLibreMap | null = null;
	private gl: WebGLRenderingContext | null = null;
	private prog: WebGLProgram | null = null;
	private buf: WebGLBuffer | null = null;
	private count = 0;
	private pending: Model3D[] = [];
	private dirty = false;
	private picks = new PickQueue<number>(0);
	/** The selected map node's (or landmark's) pick code: its models are drawn lit up; 0 for none. */
	selected = 0;
	size = 1;
	height = 1;
	far = 3;
	pos = 1e9;
	/** The haze far models fade into (rgb, 0..1; View: sky and fog), or null: none. */
	fog: [number, number, number] | null = null;

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
		this.picks.settle();
	}

	/**
	 * The model drawn at screen (x, y) css px (its pick code, 0 for none): the next frame draws each model's code as
	 * its colour into the pixel under the mouse, nearest in front as on screen (clicks were read on the flat map under
	 * the models, then from map node positions projected by hand: user).
	 */
	pickAt(x: number, y: number): Promise<number> {
		return this.picks.ask(this.map, this.count > 0, x, y);
	}

	/** Answer the waiting clicks from the frame being drawn (after the models: their depth picks the front one). */
	private pickPass(gl: WebGLRenderingContext | WebGL2RenderingContext, p: WebGLProgram, map: MapLibreMap): void {
		gl.uniform1f(gl.getUniformLocation(p, "u_pick"), 1);
		for (const req of this.picks.take()) {
			const { px, py } = pickPixel(gl, map, req.x, req.y);
			req.done(
				pickColour(
					readPickBox(gl, px, py, 1, 1, () => gl.drawArrays(gl.TRIANGLES, 0, this.count)),
					0,
				),
			);
		}
		gl.uniform1f(gl.getUniformLocation(p, "u_pick"), 0);
	}

	setModels(models: Model3D[]): void {
		this.pending = models;
		this.dirty = true;
		this.map?.triggerRepaint();
	}

	private upload(): void {
		const gl = this.gl;
		if (!gl || !this.buf) return;
		const out: number[] = [];
		for (const m of this.pending) {
			const a = MercatorCoordinate.fromLngLat(m.anchor);
			const toZ = a.meterInMercatorCoordinateUnits();
			const z0 = m.base * toZ;
			const z1 = m.height * toZ;
			const [r, g, b] = m.colour;
			const pk = [m.pick & 255, (m.pick >> 8) & 255, (m.pick >> 16) & 255].map((v) => v / 255);
			const rings = m.rings.map((ring) => {
				const pts = ring.map((p) => MercatorCoordinate.fromLngLat(p));
				// drop the closing point
				if (pts.length > 1 && pts[0].x === pts[pts.length - 1].x && pts[0].y === pts[pts.length - 1].y) pts.pop();
				return pts;
			});
			const v = (p: MercatorCoordinate, z: number, n: [number, number, number]) =>
				out.push(p.x, p.y, z, a.x, a.y, r, g, b, n[0], n[1], n[2], m.step, pk[0], pk[1], pk[2]);
			// walls of every ring
			for (const pts of rings)
				for (let i = 0; i < pts.length; i++) {
					const p = pts[i];
					const q = pts[(i + 1) % pts.length];
					const n: [number, number, number] = [q.y - p.y, -(q.x - p.x), 0];
					v(p, z0, n);
					v(q, z0, n);
					v(q, z1, n);
					v(p, z0, n);
					v(q, z1, n);
					v(p, z1, n);
				}
			// the top: a fan of the outer ring, or a strip between outer ring and hole when they match (walls of a
			// city ring)
			const up: [number, number, number] = [0, 0, 1];
			const outer = rings[0] ?? [];
			const hole = rings[1];
			if (hole && hole.length === outer.length) {
				const inner = [...hole].reverse();
				for (let i = 0; i < outer.length; i++) {
					const j = (i + 1) % outer.length;
					v(outer[i], z1, up);
					v(outer[j], z1, up);
					v(inner[j], z1, up);
					v(outer[i], z1, up);
					v(inner[j], z1, up);
					v(inner[i], z1, up);
				}
			} else
				for (let i = 1; i + 1 < outer.length; i++) {
					v(outer[0], z1, up);
					v(outer[i], z1, up);
					v(outer[i + 1], z1, up);
				}
		}
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(out), gl.STATIC_DRAW);
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
		this.count = out.length / STRIDE;
		this.dirty = false;
	}

	render(gl: WebGLRenderingContext | WebGL2RenderingContext, options: CustomRenderMethodInput): void {
		if (!this.prog || !this.map) return;
		if (this.dirty) this.upload();
		if (!this.count) {
			this.picks.settle(); // nothing drawn: nothing clicked
			return;
		}
		const p = this.prog;
		const M = options.defaultProjectionData.mainMatrix as Float32Array;
		const c = MercatorCoordinate.fromLngLat(this.map.getCenter());
		const w0 = M[3] * c.x + M[7] * c.y + M[15];
		// biome-ignore lint/correctness/useHookAtTopLevel: WebGL's useProgram, not a React hook
		gl.useProgram(p);
		gl.uniformMatrix4fv(gl.getUniformLocation(p, "u_m"), false, M);
		gl.uniform1f(gl.getUniformLocation(p, "u_size"), this.size);
		gl.uniform1f(gl.getUniformLocation(p, "u_height"), this.height);
		gl.uniform1f(gl.getUniformLocation(p, "u_far"), this.far * w0);
		gl.uniform1f(gl.getUniformLocation(p, "u_pos"), this.pos);
		const sel = this.selected;
		gl.uniform3f(
			gl.getUniformLocation(p, "u_sel"),
			(sel & 255) / 255,
			((sel >> 8) & 255) / 255,
			((sel >> 16) & 255) / 255,
		);
		gl.uniform1f(gl.getUniformLocation(p, "u_selOn"), sel > 0 ? 1 : 0);
		gl.uniform1f(gl.getUniformLocation(p, "u_fogOn"), this.fog ? 1 : 0);
		gl.uniform3f(gl.getUniformLocation(p, "u_fogCol"), ...(this.fog ?? [0, 0, 0]));
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		const attrs: [string, number, number][] = [
			["a_pos", 3, 0],
			["a_anchor", 2, 3],
			["a_col", 3, 5],
			["a_normal", 3, 8],
			["a_step", 1, 11],
			["a_pick", 3, 12],
		];
		for (const [name, size, off] of attrs) {
			const loc = gl.getAttribLocation(p, name);
			gl.enableVertexAttribArray(loc);
			gl.vertexAttribPointer(loc, size, gl.FLOAT, false, STRIDE * 4, off * 4);
		}
		gl.enable(gl.DEPTH_TEST);
		gl.depthFunc(gl.LEQUAL);
		gl.depthMask(true);
		gl.disable(gl.BLEND);
		gl.disable(gl.CULL_FACE); // rings wind either way: both sides drawn
		gl.uniform1f(gl.getUniformLocation(p, "u_pick"), 0);
		gl.drawArrays(gl.TRIANGLES, 0, this.count);
		if (this.picks.pending) this.pickPass(gl, p, this.map);
		for (const [name] of attrs) gl.disableVertexAttribArray(gl.getAttribLocation(p, name));
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
	}
}
