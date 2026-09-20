import { useEffect, useRef, useState } from 'react';
import { Mesh, Program, Renderer, Triangle } from 'ogl';
import './GradientWaves.css';

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

const hexToRgb = (hex) => {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return [1, 1, 1];
  return [
    parseInt(result[1], 16) / 255,
    parseInt(result[2], 16) / 255,
    parseInt(result[3], 16) / 255,
  ];
};

const detailToSteps = (detail) => {
  if (detail === 'low') return 40;
  if (detail === 'high') return 110;
  return 70;
};

const vertex = `#version 300 es
in vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const fragment = `#version 300 es
precision highp float;
uniform vec2 iResolution;
uniform float iTime;
uniform float uSpeed;
uniform float uAmplitude;
uniform float uWaveScale;
uniform float uWaveRatio;
uniform float uSwell;
uniform float uTurbulence;
uniform float uTilt;
uniform float uZoom;
uniform float uHeight;
uniform float uFogDepth;
uniform float uSteps;
uniform float uBrightness;
uniform float uOpacity;
uniform float uGrain;
uniform float uGrainIntensity;
uniform vec2 uMouse;
uniform float uParallax;
uniform bool uEnableMouse;
uniform vec3 uHorizonColor;
uniform vec3 uWaveColor;
uniform vec3 uCrestColor;
out vec4 fragColor;

const float MAX_DIST = 20000.0;

float hash21(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

float plasma(vec3 r, vec2 freq, vec4 tc) {
  float mx = r.x + tc.x;
  mx += uSwell * sin((r.y + mx) / 20.0 + tc.y);
  float my = r.y - tc.z;
  my += uTurbulence * cos(r.x / 23.0 + tc.w);
  return r.z - (sin(mx * freq.x) * uAmplitude + sin(my * freq.y) * uAmplitude + uHeight);
}

float raymarch(vec3 pos, vec3 dir, vec2 freq, vec4 tc) {
  float dist = 0.0;
  for (int i = 0; i < 128; i++) {
    if (float(i) >= uSteps) break;
    float dscene = plasma(pos + dist * dir, freq, tc);
    if (abs(dscene) < 0.1) break;
    dist += 0.9 * dscene;
    if (!(abs(dist) < MAX_DIST)) return MAX_DIST;
  }
  return dist;
}

void main() {
  float T = iTime * uSpeed;
  vec2 freq = vec2(uWaveScale / 7.0, (uWaveScale * uWaveRatio) / 3.0);
  vec4 tc = vec4(T / 0.130, T / 0.810, T / 0.200, T / 0.710);
  float c, s;
  float vfov = (3.14159 / 2.3) / max(uZoom, 0.05);
  vec3 cam = vec3(0.0, 0.0, 30.0);
  vec2 uv = (gl_FragCoord.xy / iResolution.xy) - 0.5;
  uv.x *= iResolution.x / iResolution.y;
  uv.y *= -1.0;

  vec3 dir = vec3(0.0, 0.0, -1.0);
  float ulen = length(uv);
  float xrot = vfov * ulen;
  c = cos(xrot); s = sin(xrot);
  dir = mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c) * dir;
  vec2 nuv = ulen > 1e-5 ? uv / ulen : vec2(1.0, 0.0);
  c = nuv.x; s = nuv.y;
  dir = mat3(c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0) * dir;
  c = cos(uTilt); s = sin(uTilt);
  dir = mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c) * dir;

  if (uEnableMouse) {
    float yaw = (uMouse.x - 0.5) * uParallax * 0.4;
    float pitch = (uMouse.y - 0.5) * uParallax * 0.4;
    c = cos(yaw); s = sin(yaw);
    dir = mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c) * dir;
    c = cos(pitch); s = sin(pitch);
    dir = mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c) * dir;
  }

  float dist = raymarch(cam, dir, freq, tc);
  vec3 pos = cam + dist * dir;
  float t = clamp(uFogDepth / max(dist, 0.001), 0.0, 1.0);
  vec3 body = mix(uWaveColor, uCrestColor, clamp(pos.z * 0.08 + 0.5, 0.0, 1.0));
  vec3 col = mix(uHorizonColor, body, t);
  col = clamp(col * uBrightness, 0.0, 1.0);
  float alpha = clamp(t, 0.0, 1.0) * uOpacity;
  if (uGrain > 0.5) {
    float g = hash21(gl_FragCoord.xy + mod(iTime, 64.0) * 11.0);
    alpha += (g - 0.5) * uGrainIntensity;
  }
  alpha = clamp(alpha, 0.0, 1.0);
  fragColor = vec4(col * alpha, alpha);
}
`;

const contexts = new WeakMap();

function prefersReducedMotion() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

function hasWebGL2() {
  if (typeof WebGL2RenderingContext === 'undefined') return false;
  try {
    const probe = document.createElement('canvas');
    const context = probe.getContext('webgl2');
    context?.getExtension('WEBGL_lose_context')?.loseContext();
    return Boolean(context);
  } catch {
    return false;
  }
}

export default function GradientWaves({
  horizonColor = '#E7DDFF',
  waveColor = '#FF9B87',
  crestColor = '#FFF7F0',
  speed = 0.18,
  amplitude = 1.8,
  waveScale = 0.6,
  waveRatio = 0.9,
  swell = 35,
  turbulence = 20,
  tilt = 1.11,
  zoom = 1,
  height = 5.5,
  fogDepth = 15,
  detail = 'low',
  brightness = 1,
  opacity = 1,
  mouseInteraction = false,
  parallaxStrength = 0.5,
  grain = true,
  grainIntensity = 0.035,
  className = '',
}) {
  const containerRef = useRef(null);
  const enableMouseRef = useRef(mouseInteraction);
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);
  const [webGLAvailable, setWebGLAvailable] = useState(null);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const media = window.matchMedia(REDUCED_MOTION_QUERY);
    const onChange = (event) => setReducedMotion(event.matches);
    media.addEventListener?.('change', onChange);
    return () => media.removeEventListener?.('change', onChange);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || reducedMotion) {
      setWebGLAvailable(reducedMotion ? false : null);
      return undefined;
    }
    if (!hasWebGL2()) {
      setWebGLAvailable(false);
      return undefined;
    }

    let renderer;
    try {
      renderer = new Renderer({
        webgl: 2,
        alpha: true,
        premultipliedAlpha: true,
        antialias: false,
        dpr: Math.min(window.devicePixelRatio || 1, 1.5),
      });
    } catch {
      setWebGLAvailable(false);
      return undefined;
    }

    setWebGLAvailable(true);
    const gl = renderer.gl;
    gl.clearColor(0, 0, 0, 0);
    const canvas = gl.canvas;
    canvas.setAttribute('aria-hidden', 'true');
    canvas.tabIndex = -1;
    container.appendChild(canvas);

    const geometry = new Triangle(gl);
    const program = new Program(gl, {
      vertex,
      fragment,
      uniforms: {
        iTime: { value: 0 },
        iResolution: { value: new Float32Array([1, 1]) },
        uSpeed: { value: 0.18 },
        uAmplitude: { value: 1.8 },
        uWaveScale: { value: 0.6 },
        uWaveRatio: { value: 0.9 },
        uSwell: { value: 35 },
        uTurbulence: { value: 20 },
        uTilt: { value: 1.11 },
        uZoom: { value: 1 },
        uHeight: { value: 5.5 },
        uFogDepth: { value: 15 },
        uSteps: { value: 40 },
        uBrightness: { value: 1 },
        uOpacity: { value: 1 },
        uGrain: { value: 1 },
        uGrainIntensity: { value: 0.035 },
        uMouse: { value: new Float32Array([0.5, 0.5]) },
        uParallax: { value: 0.5 },
        uEnableMouse: { value: false },
        uHorizonColor: { value: new Float32Array([1, 1, 1]) },
        uWaveColor: { value: new Float32Array([1, 1, 1]) },
        uCrestColor: { value: new Float32Array([1, 1, 1]) },
      },
    });
    const mesh = new Mesh(gl, { geometry, program });
    contexts.set(container, { program });

    const setSize = () => {
      const rect = container.getBoundingClientRect();
      renderer.setSize(Math.max(1, Math.floor(rect.width)), Math.max(1, Math.floor(rect.height)));
      program.uniforms.iResolution.value[0] = gl.drawingBufferWidth;
      program.uniforms.iResolution.value[1] = gl.drawingBufferHeight;
      renderer.render({ scene: mesh });
    };

    const resizeObserver = typeof ResizeObserver === 'function'
      ? new ResizeObserver(setSize)
      : null;
    resizeObserver?.observe(container);
    if (!resizeObserver) window.addEventListener('resize', setSize);
    setSize();

    let animationFrame = 0;
    let elementVisible = true;
    let pageVisible = !document.hidden;
    const startedAt = performance.now();

    const loop = (time) => {
      program.uniforms.iTime.value = (time - startedAt) * 0.001;
      renderer.render({ scene: mesh });
      animationFrame = requestAnimationFrame(loop);
    };
    const stop = () => {
      if (animationFrame) cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    };
    const start = () => {
      if (elementVisible && pageVisible && !animationFrame) {
        animationFrame = requestAnimationFrame(loop);
      }
    };

    const intersectionObserver = typeof IntersectionObserver === 'function'
      ? new IntersectionObserver(([entry]) => {
        elementVisible = entry.isIntersecting;
        if (elementVisible) start();
        else stop();
      })
      : null;
    intersectionObserver?.observe(container);

    const onVisibilityChange = () => {
      pageVisible = !document.hidden;
      if (pageVisible) start();
      else stop();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    start();

    return () => {
      stop();
      resizeObserver?.disconnect();
      intersectionObserver?.disconnect();
      if (!resizeObserver) window.removeEventListener('resize', setSize);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      contexts.delete(container);
      canvas.remove();
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    };
  }, [reducedMotion]);

  useEffect(() => {
    const context = contexts.get(containerRef.current);
    if (!context) return;
    const uniforms = context.program.uniforms;
    enableMouseRef.current = mouseInteraction;
    uniforms.uSpeed.value = speed;
    uniforms.uAmplitude.value = amplitude;
    uniforms.uWaveScale.value = waveScale;
    uniforms.uWaveRatio.value = waveRatio;
    uniforms.uSwell.value = swell;
    uniforms.uTurbulence.value = turbulence;
    uniforms.uTilt.value = tilt;
    uniforms.uZoom.value = zoom;
    uniforms.uHeight.value = height;
    uniforms.uFogDepth.value = fogDepth;
    uniforms.uSteps.value = detailToSteps(detail);
    uniforms.uBrightness.value = brightness;
    uniforms.uOpacity.value = opacity;
    uniforms.uGrain.value = grain ? 1 : 0;
    uniforms.uGrainIntensity.value = grainIntensity;
    uniforms.uParallax.value = parallaxStrength;
    uniforms.uEnableMouse.value = mouseInteraction;
    [
      ['uHorizonColor', horizonColor],
      ['uWaveColor', waveColor],
      ['uCrestColor', crestColor],
    ].forEach(([name, color]) => {
      const rgb = hexToRgb(color);
      uniforms[name].value.set(rgb);
    });
  }, [
    amplitude,
    brightness,
    crestColor,
    detail,
    fogDepth,
    grain,
    grainIntensity,
    height,
    horizonColor,
    mouseInteraction,
    opacity,
    parallaxStrength,
    speed,
    swell,
    tilt,
    turbulence,
    waveColor,
    waveRatio,
    waveScale,
    zoom,
    webGLAvailable,
  ]);

  const staticFallback = reducedMotion || webGLAvailable === false;
  return (
    <div
      ref={containerRef}
      className={`gradient-waves-container ${className}`.trim()}
      aria-hidden="true"
      data-motion={staticFallback ? 'static' : 'animated'}
    />
  );
}
