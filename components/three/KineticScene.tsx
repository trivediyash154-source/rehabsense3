"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { RoundedBox, Environment, Lightformer } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import * as THREE from "three";
import type { Theme } from "@/lib/theme";
import type { SceneMode } from "./SceneLayer";

type Tier = "low" | "high";

type Props = {
  theme: Theme;
  tier: Tier;
  running: boolean;
  mode: SceneMode;
  showProduct: boolean;
  onFailure: () => void;
};

/* ------------------------------------------------------------------ *
 * Scene grammar
 *
 * Every mode is a set of target values that the ribbons damp toward, so
 * transitions are continuous rather than cut. The metaphor is fixed:
 * ribbon 0 and 1 are the left and right limb, everything else is context.
 * ------------------------------------------------------------------ */

type ModeState = {
  opacity: number;   // overall presence
  gap: number;       // signal fragmentation (the space between appointments)
  orbit: number;     // straight flow -> circular, explainable orbit
  sync: number;      // bilateral divergence -> alignment
  station: number;   // sequential node activation along the path
  speed: number;     // pulse travel rate
  spreadX: number;   // horizontal placement of the ribbon field
  scale: number;
};

const MODE_STATE: Record<SceneMode, ModeState> = {
  hero:     { opacity: 0.82, gap: 0.00, orbit: 0.00, sync: 0.45, station: 0.0, speed: 1.00, spreadX: 3.35, scale: 1.00 },
  gap:      { opacity: 0.42, gap: 1.00, orbit: 0.00, sync: 0.00, station: 0.0, speed: 0.55, spreadX: 2.30, scale: 0.96 },
  flow:     { opacity: 0.78, gap: 0.00, orbit: 0.12, sync: 0.80, station: 1.0, speed: 1.35, spreadX: 2.55, scale: 0.98 },
  features: { opacity: 0.62, gap: 0.00, orbit: 0.05, sync: 1.00, station: 0.3, speed: 0.95, spreadX: 2.95, scale: 0.94 },
  score:    { opacity: 0.85, gap: 0.00, orbit: 1.00, sync: 1.00, station: 0.0, speed: 0.75, spreadX: 2.40, scale: 0.90 },
  contact:  { opacity: 0.58, gap: 0.00, orbit: 0.35, sync: 1.00, station: 0.0, speed: 0.50, spreadX: 1.70, scale: 0.72 },
};

/* Palettes are authored per theme, never derived by inverting the other. */
const DARK_PALETTES: Record<SceneMode, string[]> = {
  hero:     ["#38e8ff", "#7cb0ff", "#a98cff", "#e26fd3"],
  gap:      ["#4d6a92", "#5b7fae", "#7d7bb8", "#4a6f8f"],
  flow:     ["#38e8ff", "#38e0b5", "#5aa0ff", "#8ce4ff"],
  features: ["#4ad8ff", "#5f9dff", "#9b8cff", "#38e0b5"],
  score:    ["#38e0b5", "#a98cff", "#e6b169", "#38e8ff"],
  contact:  ["#ff9f8e", "#b79aff", "#54d8c2", "#f0c07f"],
};

const LIGHT_PALETTES: Record<SceneMode, string[]> = {
  hero:     ["#0091b8", "#2c63d8", "#6a4fd0", "#b0399f"],
  gap:      ["#8a9cb2", "#93a4b8", "#9a95bd", "#8fa3b6"],
  flow:     ["#0091b8", "#00897a", "#2c63d8", "#0aa0c4"],
  features: ["#0091b8", "#2c63d8", "#6a4fd0", "#00897a"],
  score:    ["#00897a", "#6a4fd0", "#a56b25", "#0091b8"],
  contact:  ["#b8534a", "#6a4fd0", "#00897a", "#a56b25"],
};

/* ------------------------------------------------------------------ *
 * Ribbon shader
 *
 * The pulse travels along the tube's length (uv.x) rather than the whole
 * object moving. Additional layers: a fine sampling comb (the "sensor
 * reading" texture), a periodic bilateral synchronisation flash, a
 * fragmentation mask for the problem section, and depth-based fade so
 * ribbons recede into atmosphere instead of ending abruptly.
 * ------------------------------------------------------------------ */

const vertexShader = /* glsl */ `
attribute vec3 aOrbit;
uniform float uOrbit;
uniform float uSync;
uniform float uLimb;      // -1 left, +1 right, 0 context
uniform float uTime;
varying vec2 vUv;
varying float vDepth;

void main() {
  // Straight signal flow morphs into a closed, explainable orbit.
  vec3 p = mix(position, aOrbit, uOrbit);

  // Bilateral divergence: the two limb ribbons drift apart, then converge
  // as synchronisation increases. A tiny residual asymmetry is kept —
  // real gait is never perfectly symmetric.
  float drift = (1.0 - uSync) * uLimb * 0.42;
  p.x += drift;
  p.z += drift * 0.35;
  p.y += sin(uTime * 0.35 + position.y * 0.4) * (1.0 - uSync) * uLimb * 0.10;

  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vDepth = -mv.z;
  vUv = uv;
  gl_Position = projectionMatrix * mv;
}
`;

const fragmentShader = /* glsl */ `
precision highp float;

uniform float uTime;
uniform float uIndex;
uniform float uOpacity;
uniform float uGap;
uniform float uStation;
uniform float uSpeed;
uniform float uLimb;
uniform float uSync;
uniform float uGlow;      // 1.0 dark (additive), lower in daylight
uniform vec3  uColor;
uniform vec3  uAccent;

varying vec2 vUv;
varying float vDepth;

float gaussian(float x, float sigma) {
  return exp(-(x * x) / (2.0 * sigma * sigma));
}

void main() {
  float t = uTime * uSpeed;

  // --- travelling pulse: two packets per ribbon, offset in phase --------
  float lane = uIndex * 0.137;
  float head1 = fract(vUv.x * 1.0 - t * 0.115 - lane);
  float head2 = fract(vUv.x * 1.0 - t * 0.077 - lane - 0.5);
  float packet = gaussian(head1 - 0.5, 0.045) + 0.6 * gaussian(head2 - 0.5, 0.03);

  // Trailing comet tail behind each packet.
  float tail = smoothstep(0.0, 0.32, head1) * gaussian(head1 - 0.5, 0.22) * 0.35;

  // --- sampling comb: the signal is discretely sampled ------------------
  float comb = pow(max(0.0, sin(vUv.x * 210.0 - t * 4.0)), 26.0) * 0.28;

  // --- sequential station activation (sensor -> analytics core) ---------
  float stations = 0.0;
  if (uStation > 0.001) {
    float phase = fract(t * 0.22);
    for (float i = 0.0; i < 4.0; i += 1.0) {
      float at = 0.18 + i * 0.22;
      float lit = gaussian(fract(phase - i * 0.16) - 0.12, 0.09);
      stations += gaussian(vUv.x - at, 0.014) * lit * 2.2;
    }
    stations *= uStation;
  }

  // --- bilateral synchronisation flash ---------------------------------
  float beat = pow(max(0.0, sin(uTime * 0.55)), 40.0);
  float flash = beat * mix(0.10, 0.42, uSync) * step(abs(uLimb), 0.5 + abs(uLimb));

  // --- fragmentation: information missing between appointments ---------
  float shard = smoothstep(0.20, 0.44, fract(vUv.x * 6.0 + uIndex * 0.31));
  float broken = mix(1.0, shard, uGap);

  // --- shaping ----------------------------------------------------------
  float edge = pow(max(0.0, sin(vUv.y * 3.14159265)), 0.55);   // soft tube edges
  float depth = 1.0 - smoothstep(8.0, 24.0, vDepth);            // atmospheric fade
  float ends = smoothstep(0.0, 0.10, vUv.x) * smoothstep(1.0, 0.90, vUv.x);

  float energy = packet + tail + comb + stations;
  float alpha = (0.085 + energy * 0.85 + flash) * edge * depth * ends * broken * uOpacity;

  // Hot core reads white-ish at the packet centre, accent colour in the tail.
  vec3 colour = mix(uColor, uAccent, clamp(tail * 2.2 + stations * 0.4, 0.0, 1.0));
  colour += vec3(1.0) * packet * 0.34 * uGlow;
  colour *= 1.0 + energy * 1.15 * uGlow;

  gl_FragColor = vec4(colour, clamp(alpha, 0.0, 1.0));
}
`;

/** Builds the flow tube plus a matching orbital target for vertex morphing. */
function useRibbonGeometry(index: number, isLimb: boolean, tier: Tier) {
  return useMemo(() => {
    const tubular = tier === "low" ? 110 : 220;
    const radial = tier === "low" ? 4 : 6;
    const radius = isLimb ? 0.028 : 0.013 + (index % 3) * 0.004;

    const phase = isLimb ? index * 0.16 : index * 0.83;
    const spread = isLimb ? 1.35 : 0.85 + ((index * 37) % 11) * 0.11;

    const flowPoints: THREE.Vector3[] = [];
    const orbitPoints: THREE.Vector3[] = [];
    const steps = 72;
    const orbitRadius = isLimb ? 2.05 + index * 0.16 : 1.15 + ((index * 29) % 13) * 0.13;

    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      flowPoints.push(
        new THREE.Vector3(
          Math.sin(t * Math.PI * 2 + phase) * spread + (isLimb ? (index - 0.5) * 0.34 : 0),
          -4.9 + t * 9.4,
          Math.sin(t * Math.PI * 4 + phase * 1.7) * 0.8 - (index % 5) * 0.16,
        ),
      );
      // Closed ring in the view plane: the "explainable" orbital state.
      const a = t * Math.PI * 2 + phase;
      orbitPoints.push(
        new THREE.Vector3(
          Math.cos(a) * orbitRadius,
          Math.sin(a) * orbitRadius * 0.92,
          Math.sin(a * 3.0 + phase) * 0.24,
        ),
      );
    }

    const flowCurve = new THREE.CatmullRomCurve3(flowPoints);
    const orbitCurve = new THREE.CatmullRomCurve3(orbitPoints, true);

    const geometry = new THREE.TubeGeometry(flowCurve, tubular, radius, radial, false);
    const orbitGeometry = new THREE.TubeGeometry(orbitCurve, tubular, radius, radial, false);
    // Same topology, so the position buffer transfers vertex-for-vertex.
    geometry.setAttribute("aOrbit", orbitGeometry.attributes.position.clone());
    orbitGeometry.dispose();

    return { geometry, flowCurve, orbitCurve };
  }, [index, isLimb, tier]);
}

function Ribbon({
  index,
  theme,
  mode,
  tier,
  isLimb,
}: {
  index: number;
  theme: Theme;
  mode: SceneMode;
  tier: Tier;
  isLimb: boolean;
}) {
  const material = useRef<THREE.ShaderMaterial>(null);
  const group = useRef<THREE.Group>(null);
  const particles = useRef<THREE.Group>(null);
  const { geometry, flowCurve, orbitCurve } = useRibbonGeometry(index, isLimb, tier);

  const colour = useMemo(() => new THREE.Color(), []);
  const accent = useMemo(() => new THREE.Color(), []);
  const point = useMemo(() => new THREE.Vector3(), []);
  const orbitPoint = useMemo(() => new THREE.Vector3(), []);

  const particleCount = tier === "low" ? (isLimb ? 2 : 0) : isLimb ? 4 : 1;

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uIndex: { value: index },
      uOpacity: { value: 0 },
      uGap: { value: 0 },
      uOrbit: { value: 0 },
      uSync: { value: 1 },
      uStation: { value: 0 },
      uSpeed: { value: 1 },
      uLimb: { value: isLimb ? (index === 0 ? -1 : 1) : 0 },
      uGlow: { value: 1 },
      uColor: { value: new THREE.Color("#38e8ff") },
      uAccent: { value: new THREE.Color("#a98cff") },
    }),
    [index, isLimb],
  );

  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    const target = MODE_STATE[mode];
    const palette = theme === "dark" ? DARK_PALETTES[mode] : LIGHT_PALETTES[mode];
    const d = Math.min(delta, 0.1); // clamp after a tab regains focus

    const u = material.current?.uniforms;
    if (u) {
      u.uTime.value = t;
      colour.set(palette[index % palette.length]);
      accent.set(palette[(index + 2) % palette.length]);
      u.uColor.value.lerp(colour, d * 1.6);
      u.uAccent.value.lerp(accent, d * 1.6);

      // Daylight: no additive blow-out, lower presence, deeper hues.
      const themeScale = theme === "light" ? 0.62 : 1;
      // The two limb ribbons carry the metaphor; context strands stay quiet,
      // and quieter still on phones where they share space with the copy.
      const limbBoost = isLimb ? 1 : tier === "low" ? 0.34 : 0.55;

      u.uOpacity.value = THREE.MathUtils.damp(
        u.uOpacity.value,
        target.opacity * themeScale * limbBoost,
        2.2,
        d,
      );
      u.uGap.value = THREE.MathUtils.damp(u.uGap.value, target.gap, 2.6, d);
      u.uOrbit.value = THREE.MathUtils.damp(u.uOrbit.value, target.orbit, 1.7, d);
      u.uSync.value = THREE.MathUtils.damp(u.uSync.value, target.sync, 1.4, d);
      u.uStation.value = THREE.MathUtils.damp(u.uStation.value, target.station, 2.4, d);
      u.uSpeed.value = THREE.MathUtils.damp(u.uSpeed.value, target.speed, 2, d);
      u.uGlow.value = theme === "dark" ? 1 : 0.28;
    }

    if (group.current) {
      const scrolled = Math.min(window.scrollY / Math.max(window.innerHeight, 1), 9);
      group.current.position.x = THREE.MathUtils.damp(
        group.current.position.x,
        tier === "low" ? target.spreadX * 0.62 : target.spreadX,
        1.4,
        d,
      );
      group.current.position.y =
        Math.sin(t * 0.12 + index * 0.09) * 0.14 - scrolled * 0.03;
      group.current.rotation.z = THREE.MathUtils.damp(
        group.current.rotation.z,
        Math.sin(t * 0.06 + index * 0.11) * 0.13,
        1.4,
        d,
      );
      const s = THREE.MathUtils.damp(
        group.current.scale.x,
        target.scale * (tier === "low" ? 0.82 : 1),
        1.3,
        d,
      );
      group.current.scale.setScalar(s);
    }

    // Particles ride the same path the pulse travels, so the light and the
    // matter agree with each other.
    if (particles.current && particleCount > 0) {
      const orbitMix = material.current?.uniforms.uOrbit.value ?? 0;
      particles.current.children.forEach((child, i) => {
        const offset = i / particleCount;
        const at = (t * (0.05 + index * 0.004) + offset + index * 0.11) % 1;
        flowCurve.getPointAt(at, point);
        orbitCurve.getPointAt(at, orbitPoint);
        child.position.lerpVectors(point, orbitPoint, orbitMix);
        const material2 = (child as THREE.Mesh).material as THREE.MeshBasicMaterial;
        material2.opacity = (0.5 + Math.sin(t * 2 + i) * 0.2) * (theme === "light" ? 0.45 : 1);
      });
    }
  });

  return (
    <group ref={group} position={[2.7, 0, -1]}>
      <mesh geometry={geometry} frustumCulled={false}>
        <shaderMaterial
          ref={material}
          uniforms={uniforms}
          vertexShader={vertexShader}
          fragmentShader={fragmentShader}
          transparent
          depthWrite={false}
          side={THREE.DoubleSide}
          blending={theme === "dark" ? THREE.AdditiveBlending : THREE.NormalBlending}
        />
      </mesh>
      <group ref={particles}>
        {Array.from({ length: particleCount }, (_, i) => (
          <mesh key={i}>
            <sphereGeometry args={[isLimb ? 0.032 : 0.018, 8, 8]} />
            <meshBasicMaterial
              color={index % 2 ? "#a98cff" : "#38e8ff"}
              transparent
              opacity={0.7}
              toneMapped={false}
            />
          </mesh>
        ))}
      </group>
    </group>
  );
}

/** Atmospheric dust. Gives the volume something to be measured against. */
function Motes({ tier, theme }: { tier: Tier; theme: Theme }) {
  const points = useRef<THREE.Points>(null);
  const count = tier === "low" ? 90 : 260;

  const geometry = useMemo(() => {
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = (Math.random() - 0.2) * 16;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 13;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 9 - 2;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return g;
  }, [count]);

  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame((state) => {
    if (!points.current) return;
    const t = state.clock.elapsedTime;
    points.current.rotation.y = t * 0.008;
    points.current.position.y = Math.sin(t * 0.09) * 0.3;
  });

  return (
    <points ref={points} geometry={geometry} frustumCulled={false}>
      <pointsMaterial
        size={theme === "dark" ? 0.028 : 0.022}
        color={theme === "dark" ? "#9fd8ff" : "#4d7ea8"}
        transparent
        opacity={theme === "dark" ? 0.5 : 0.28}
        sizeAttenuation
        depthWrite={false}
        blending={theme === "dark" ? THREE.AdditiveBlending : THREE.NormalBlending}
      />
    </points>
  );
}

/* ------------------------------------------------------------------ *
 * Product: a wearable sensing assembly, not an anatomy model.
 * Thigh and shin segments read as a transparent brace structure; the
 * sensor modules are the solid, engineered objects.
 * ------------------------------------------------------------------ */

type Focus = "thigh" | "shin" | "sync" | "score";

function SensorModule({
  active,
  scale = 1,
  onFocus,
}: {
  active: boolean;
  scale?: number;
  onFocus: () => void;
}) {
  const led = useRef<THREE.MeshStandardMaterial>(null);
  const halo = useRef<THREE.Mesh>(null);

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    if (led.current) {
      const target = active ? 6.5 + Math.sin(t * 5) * 1.4 : 1.6 + Math.sin(t * 1.6) * 0.4;
      led.current.emissiveIntensity = THREE.MathUtils.damp(
        led.current.emissiveIntensity,
        target,
        4,
        Math.min(delta, 0.1),
      );
    }
    if (halo.current) {
      const s = THREE.MathUtils.damp(halo.current.scale.x, active ? 1 : 0.001, 5, Math.min(delta, 0.1));
      halo.current.scale.setScalar(s);
      const m = halo.current.material as THREE.MeshBasicMaterial;
      // Kept low: this is a focus cue, not a light source. A brighter disc
      // blooms across the whole module and hides the hardware.
      m.opacity = active ? 0.07 + Math.sin(t * 4) * 0.02 : 0;
    }
  });

  return (
    <group
      scale={scale}
      onPointerOver={(event) => {
        event.stopPropagation();
        onFocus();
      }}
    >
      {/* enclosure */}
      <RoundedBox args={[0.62, 0.88, 0.24]} radius={0.09} smoothness={4}>
        <meshStandardMaterial color="#131f33" metalness={0.85} roughness={0.28} />
      </RoundedBox>
      {/* faceplate */}
      <RoundedBox args={[0.5, 0.74, 0.02]} radius={0.06} position={[0, 0, 0.13]}>
        <meshStandardMaterial color="#1b2d45" metalness={0.65} roughness={0.22} />
      </RoundedBox>
      {/* machined seam */}
      <mesh position={[0, 0, 0.1]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.27, 0.006, 6, 40]} />
        <meshStandardMaterial color="#456a8c" metalness={0.9} roughness={0.3} />
      </mesh>
      {/* status LED bar */}
      <mesh position={[0, 0.24, 0.15]}>
        <boxGeometry args={[0.2, 0.022, 0.02]} />
        <meshStandardMaterial ref={led} color="#38e8ff" emissive="#38e8ff" emissiveIntensity={2} toneMapped={false} />
      </mesh>
      {/* IMU aperture */}
      <mesh position={[0, -0.13, 0.15]}>
        <ringGeometry args={[0.07, 0.084, 28]} />
        <meshBasicMaterial color="#7f9cba" />
      </mesh>
      {/* focus halo */}
      <mesh ref={halo} position={[0, 0, 0.16]} scale={0.001}>
        <ringGeometry args={[0.33, 0.42, 40]} />
        <meshBasicMaterial color="#38e8ff" transparent opacity={0} depthWrite={false} />
      </mesh>
    </group>
  );
}

function Product({ tier, theme, mode }: { tier: Tier; theme: Theme; mode: SceneMode }) {
  const group = useRef<THREE.Group>(null);
  const shin = useRef<THREE.Group>(null);
  const ring = useRef<THREE.Mesh>(null);
  const ringMaterial = useRef<THREE.MeshStandardMaterial>(null);
  const beam = useRef<THREE.Mesh>(null);
  const [focus, setFocus] = useState<Focus>("sync");

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (detail === "thigh" || detail === "shin" || detail === "sync" || detail === "score") {
        setFocus(detail);
      }
    };
    window.addEventListener("rehab:focus", handler);
    return () => window.removeEventListener("rehab:focus", handler);
  }, []);

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    const d = Math.min(delta, 0.1);
    const visible = mode === "hero";

    if (group.current) {
      // Restrained float. No continuous product-viewer spin.
      const targetY = (tier === "low" ? -1.55 : 0.02) + Math.sin(t * 0.5) * 0.075;
      group.current.position.y = THREE.MathUtils.damp(group.current.position.y, targetY, 3, d);
      group.current.rotation.y = THREE.MathUtils.damp(
        group.current.rotation.y,
        -0.36 + Math.sin(t * 0.15) * 0.07 + state.pointer.x * (tier === "low" ? 0 : 0.05),
        2,
        d,
      );
      group.current.rotation.x = THREE.MathUtils.damp(
        group.current.rotation.x,
        0.04 + state.pointer.y * (tier === "low" ? 0 : -0.03),
        2,
        d,
      );
      const s = THREE.MathUtils.damp(
        group.current.scale.x,
        visible ? (tier === "low" ? 0.55 : 1.02) : 0.001,
        2.4,
        d,
      );
      group.current.scale.setScalar(Math.max(s, 0.0001));
      group.current.visible = s > 0.01;
    }

    // Controlled, slow knee flexion: range of motion made visible without
    // claiming a measured angle.
    if (shin.current) {
      const cycle = (Math.sin(t * 0.42) + 1) / 2;
      const flexion = THREE.MathUtils.lerp(0.06, 0.46, cycle) * (focus === "score" ? 0.4 : 1);
      shin.current.rotation.z = THREE.MathUtils.damp(shin.current.rotation.z, -flexion, 3, d);
    }

    if (ring.current && ringMaterial.current) {
      ring.current.rotation.z = Math.sin(t * 0.22) * 0.22;
      ring.current.rotation.x = 0.42 + Math.sin(t * 0.16) * 0.06;
      const emphasise = focus === "score";
      ringMaterial.current.emissiveIntensity = THREE.MathUtils.damp(
        ringMaterial.current.emissiveIntensity,
        emphasise ? 4.2 : 1.9,
        3,
        d,
      );
      const s = THREE.MathUtils.damp(ring.current.scale.x, emphasise ? 1.1 : 1, 3, d);
      ring.current.scale.setScalar(s);
    }

    // Bilateral link: a pulse travelling between the two sensor modules.
    if (beam.current) {
      const m = beam.current.material as THREE.MeshBasicMaterial;
      const on = focus === "sync";
      m.opacity = THREE.MathUtils.damp(
        m.opacity,
        on ? 0.55 + Math.sin(t * 3.4) * 0.25 : 0.12,
        4,
        d,
      );
      beam.current.position.y = THREE.MathUtils.lerp(-0.15, 0.95, (Math.sin(t * 1.1) + 1) / 2);
    }
  });

  const shell = (
    <meshPhysicalMaterial
      color={theme === "dark" ? "#8fc0e2" : "#4f7ba3"}
      metalness={0.1}
      roughness={0.16}
      clearcoat={1}
      clearcoatRoughness={0.12}
      transparent
      opacity={theme === "dark" ? 0.1 : 0.16}
      side={THREE.DoubleSide}
      depthWrite={false}
    />
  );

  // Straps read as machined bands rather than black voids, so the assembly
  // has visible structure against a dark background.
  const strap = (
    <meshStandardMaterial
      color={theme === "dark" ? "#22384f" : "#48607a"}
      roughness={0.55}
      metalness={0.6}
    />
  );

  return (
    <group
      ref={group}
      position={[tier === "low" ? 0.4 : 2.6, 0, 0]}
      rotation={[0.04, -0.36, -0.16]}
      scale={0.001}
    >
      {/* ---- thigh segment ---- */}
      <group position={[0, 1.15, 0]}>
        <mesh>
          <capsuleGeometry args={[0.34, 1.5, 6, 20]} />
          {shell}
        </mesh>
        {[-0.24, 0.34].map((y) => (
          <mesh key={y} position={[0, y, 0]} rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.37, 0.075, 6, 26]} />
            {strap}
          </mesh>
        ))}
        <group position={[0, 0.05, 0.44]}>
          <SensorModule active={focus === "thigh" || focus === "sync"} onFocus={() => setFocus("thigh")} />
        </group>
      </group>

      {/* ---- knee: transparent brace structure ---- */}
      <group>
        <mesh>
          <sphereGeometry args={[0.3, 24, 18]} />
          <meshPhysicalMaterial
            color="#8fd3e6"
            transparent
            opacity={theme === "dark" ? 0.17 : 0.22}
            roughness={0.08}
            clearcoat={1}
            depthWrite={false}
          />
        </mesh>
        {/* brace hinge arcs */}
        <mesh rotation={[0, Math.PI / 2, 0]}>
          <torusGeometry args={[0.42, 0.022, 6, 40, Math.PI * 1.1]} />
          <meshStandardMaterial color="#2b4a68" metalness={0.9} roughness={0.35} />
        </mesh>
      </group>

      {/* ---- shin segment (flexes) ---- */}
      <group ref={shin} position={[0, -0.05, 0]}>
        <group position={[-0.12, -1.12, 0]}>
          <mesh>
            <capsuleGeometry args={[0.27, 1.4, 6, 20]} />
            {shell}
          </mesh>
          {[-0.22, 0.32].map((y) => (
            <mesh key={y} position={[0, y, 0]} rotation={[Math.PI / 2, 0, 0]}>
              <torusGeometry args={[0.3, 0.062, 6, 26]} />
              {strap}
            </mesh>
          ))}
          <group position={[0, 0.04, 0.36]}>
            <SensorModule
              active={focus === "shin" || focus === "sync"}
              scale={0.92}
              onFocus={() => setFocus("shin")}
            />
          </group>
        </group>
      </group>

      {/* ---- bilateral link pulse ---- */}
      <mesh ref={beam} position={[0.02, 0.4, 0.42]}>
        <sphereGeometry args={[0.045, 10, 10]} />
        <meshBasicMaterial color="#38e8ff" transparent opacity={0.2} toneMapped={false} depthWrite={false} />
      </mesh>

      {/* ---- explainable recovery ring ---- */}
      <mesh ref={ring} rotation={[0.42, 0.3, 0]}>
        <torusGeometry args={[0.82, 0.014, 8, 96, Math.PI * 1.72]} />
        <meshStandardMaterial
          ref={ringMaterial}
          color="#38e8ff"
          emissive="#38e8ff"
          emissiveIntensity={2}
          toneMapped={false}
        />
      </mesh>
      <mesh rotation={[-0.62, 0.78, 0.58]}>
        <torusGeometry args={[1.05, 0.007, 6, 80, Math.PI * 1.25]} />
        <meshBasicMaterial color="#a98cff" transparent opacity={theme === "dark" ? 0.65 : 0.4} />
      </mesh>
    </group>
  );
}

function SceneContent({ theme, tier, mode, showProduct }: Omit<Props, "running" | "onFailure">) {
  const { camera } = useThree();
  const limbCount = 2;
  const contextCount = tier === "low" ? 3 : 8;

  useFrame((state, delta) => {
    const d = Math.min(delta, 0.1);
    const strength = tier === "low" ? 0 : 1;
    camera.position.x = THREE.MathUtils.damp(camera.position.x, state.pointer.x * 0.1 * strength, 1.8, d);
    camera.position.y = THREE.MathUtils.damp(camera.position.y, state.pointer.y * 0.075 * strength, 1.8, d);
    camera.lookAt(0, 0, 0);
  });

  return (
    <>
      <fog attach="fog" args={[theme === "dark" ? "#04070f" : "#eef4fa", 10, 26]} />
      <ambientLight intensity={theme === "dark" ? 0.75 : 2.1} />
      <directionalLight position={[3, 5, 6]} intensity={theme === "dark" ? 2.8 : 3.4} color="#bfe8ff" />
      <pointLight position={[4, -1.5, 2]} intensity={theme === "dark" ? 14 : 6} color="#38e8ff" distance={10} />
      <pointLight position={[0.5, 2.5, -2]} intensity={theme === "dark" ? 11 : 5} color="#a98cff" distance={9} />

      {tier === "high" && (
        <Environment resolution={96}>
          <Lightformer intensity={theme === "dark" ? 1.6 : 3} position={[0, 4, 3]} scale={[8, 2, 1]} color="#dcefff" />
          <Lightformer intensity={theme === "dark" ? 1.1 : 2} position={[-4, 0, 3]} scale={[2, 8, 1]} color="#5aa0ff" />
          <Lightformer intensity={theme === "dark" ? 0.8 : 1.6} position={[4, -2, 2]} scale={[3, 4, 1]} color="#a98cff" />
        </Environment>
      )}

      <Motes tier={tier} theme={theme} />

      {Array.from({ length: limbCount }, (_, i) => (
        <Ribbon key={`limb-${i}`} index={i} theme={theme} mode={mode} tier={tier} isLimb />
      ))}
      {Array.from({ length: contextCount }, (_, i) => (
        <Ribbon key={`ctx-${i}`} index={i + 2} theme={theme} mode={mode} tier={tier} isLimb={false} />
      ))}

      {showProduct && <Product tier={tier} theme={theme} mode={mode} />}

      {tier === "high" && (
        <EffectComposer multisampling={0} enableNormalPass={false}>
          <Bloom
            intensity={theme === "dark" ? (mode === "hero" ? 0.85 : 0.45) : 0.16}
            luminanceThreshold={theme === "dark" ? 0.62 : 0.9}
            luminanceSmoothing={0.3}
            mipmapBlur
          />
        </EffectComposer>
      )}
    </>
  );
}

export default function KineticScene(props: Props) {
  const { running, onFailure, ...rest } = props;

  return (
    <Canvas
      camera={{ position: [0, 0, 10], fov: 42 }}
      dpr={props.tier === "low" ? 1 : [1, 1.75]}
      frameloop={running ? "always" : "never"}
      gl={{
        alpha: true,
        antialias: false,
        powerPreference: "high-performance",
        failIfMajorPerformanceCaveat: false,
      }}
      onCreated={({ gl }) => {
        gl.setClearColor(0x000000, 0);
        gl.domElement.addEventListener(
          "webglcontextlost",
          (event) => {
            event.preventDefault();
            onFailure();
          },
          { once: true },
        );
      }}
      fallback={null}
    >
      <SceneContent {...rest} />
    </Canvas>
  );
}
