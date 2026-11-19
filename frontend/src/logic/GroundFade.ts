import {
	type CustomLayerInterface,
	type CustomRenderMethodInput,
	type Map as MapLibreMap,
	MercatorCoordinate,
} from "maplibre-gl";

const VS = `
attribute vec2 a_xy;
uniform mat4 u_m;
varying float v_w;
void main() {
	vec4 c = u_m * vec4(a_xy, 0.0, 1.0);
	v_w = c.w;
	gl_Position = c;
}`;

const FS = `
precision highp float;
uniform float u_from;
uniform float u_to;
varying float v_w;
void main() {
	float a = clamp((v_w - u_from) / max(u_to - u_from, 0.0001), 0.0, 1.0);
	gl_FragColor = vec4(0.0, 0.0, 0.0, a);
}`;

/**
 * The 3D view's ground fading into black far off (user: a render distance for the ground too): a sheet over the
 * whole world just above the flat layers, black by distance from the camera, from `far` times the view centre's
 * distance over half that again. Drawn under the 3D models, icons and paths (they have their own reach).
 */
export class GroundFade implements CustomLayerInterface {
	readonly id = "ground-fade-gl";
	readonly type = "custom" as const;
	readonly renderingMode = "3d" as const;
	private map: MapLibreMap | null = null;
	private prog: WebGLProgram | null = null;
	private buf: WebGLBuffer | null = null;

	constructor(private readonly far: number) {}

	onAdd(map: MapLibreMap, gl: WebGLRenderingContext | WebGL2RenderingContext): void {
		this.map = map;
		const sh = (type: number, src: string) => {
			const s = gl.createShader(type) as WebGLShader;
			gl.shaderSource(s, src);
			gl.compileShader(s);
			return s;
		};
		const p = gl.createProgram() as WebGLProgram;
		gl.attachShader(p, sh(gl.VERTEX_SHADER, VS));
		gl.attachShader(p, sh(gl.FRAGMENT_SHADER, FS));
		gl.linkProgram(p);
		this.prog = p;
		this.buf = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1]), gl.STATIC_DRAW);
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
	}

	onRemove(map: MapLibreMap, gl: WebGLRenderingContext | WebGL2RenderingContext): void {
		void map;
		if (this.prog) gl.deleteProgram(this.prog);
		if (this.buf) gl.deleteBuffer(this.buf);
		this.map = null;
	}

	render(gl: WebGLRenderingContext | WebGL2RenderingContext, options: CustomRenderMethodInput): void {
		if (!this.prog || !this.map) return;
		const M = options.defaultProjectionData.mainMatrix as Float32Array;
		const c = MercatorCoordinate.fromLngLat(this.map.getCenter());
		const w0 = M[3] * c.x + M[7] * c.y + M[15];
		const p = this.prog;
		// biome-ignore lint/correctness/useHookAtTopLevel: WebGL's useProgram, not a React hook
		gl.useProgram(p);
		gl.uniformMatrix4fv(gl.getUniformLocation(p, "u_m"), false, M);
		gl.uniform1f(gl.getUniformLocation(p, "u_from"), this.far * w0);
		gl.uniform1f(gl.getUniformLocation(p, "u_to"), this.far * 1.5 * w0);
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		const loc = gl.getAttribLocation(p, "a_xy");
		gl.enableVertexAttribArray(loc);
		gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
		gl.disable(gl.DEPTH_TEST);
		gl.enable(gl.BLEND);
		gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
		gl.drawArrays(gl.TRIANGLES, 0, 6);
		gl.disableVertexAttribArray(loc);
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
	}
}
