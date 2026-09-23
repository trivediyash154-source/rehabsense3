"use client";

import { Suspense, useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { useSceneStatus } from "@/components/three/SceneContext";

/**
 * MOVEMENT CORE
 *
 * A bilateral lower-limb instrument in real 3D. Thigh and shin are separate
 * segments hinged at the knee, so flexion is an actual rotation rather than a
 * drawing that resembles one — which is what lets the same component show a
 * recorded session, a live stream and a baseline/current overlay without
 * changing its meaning.
 *
 * Modes:
 *   overview — the selected session's peaks, breathing slowly
 *   live     — driven by the angles arriving from the backend
 *   compare  — the current limb solid, the baseline behind it as a ghost
 *
 * Every angle is supplied by the caller. Nothing here invents a measurement.
 */

export type MovementCoreMode = "overview" | "live" | "compare";

export type CoreInput = {
  /** Peak or current knee flexion per limb, in degrees. */
  left: number;
  right: number;
  /** Baseline flexion for compare mode. */
  baselineLeft?: number;
  baselineRight?: number;
  /** 0..1 — drives the halo's strength. */
  confidence?: number;
  /** Which limb was operated on; it is highlighted. */
  operated?: "LEFT" | "RIGHT" | null;
  /** Live streams animate; a recorded session breathes gently. */
  active?: boolean;
};

const CYAN = "#38e8ff";
const VIOLET = "#b097ff";
const TEAL = "#3fe0bb";
const GHOST = "#5f7599";

/** One limb: hip → thigh → knee → shin → ankle, hinged at the knee. */
function Limb({
  x,
  flex,
  colour,
  ghost = false,
  emphasis = false,
  phase = 0,
  active = true,
}: {
  x: number;
  flex: number;
  colour: string;
  ghost?: boolean;
  emphasis?: boolean;
  phase?: number;
  active?: boolean;
}) {
  const shin = useRef<THREE.Group>(null);
  const thigh = useRef<THREE.Group>(null);

  useFrame((state) => {
    if (!shin.current) return;
    // A gait cycle rides on top of the supplied peak, so the limb moves the
    // way the recorded cycle did rather than sweeping arbitrarily.
    const t = state.clock.elapsedTime;
    const swing = active ? Math.pow(Math.sin(t * 1.1 + phase), 2) : 0.55;
    const target = THREE.MathUtils.degToRad(flex * swing);
    shin.current.rotation.x = THREE.MathUtils.lerp(shin.current.rotation.x, -target, 0.12);
    if (thigh.current) {
      thigh.current.rotation.x = THREE.MathUtils.lerp(
        thigh.current.rotation.x,
        target * 0.22,
        0.12,
      );
    }
  });

  const opacity = ghost ? 0.24 : 1;
  const segment = (h: number) => new THREE.CapsuleGeometry(0.19, h, 6, 16);

  return (
    <group position={[x, 0, 0]}>
      <group ref={thigh} position={[0, 1.15, 0]}>
        {/* thigh */}
        <mesh position={[0, -0.55, 0]} geometry={segment(0.9)}>
          <meshStandardMaterial
            color={colour}
            transparent
            opacity={opacity * (ghost ? 1 : 0.9)}
            roughness={0.35}
            metalness={0.25}
            emissive={colour}
            emissiveIntensity={ghost ? 0.05 : emphasis ? 0.5 : 0.25}
            depthWrite={!ghost}
          />
        </mesh>

        {/* thigh sensor node */}
        {!ghost && (
          <mesh position={[0.22, -0.42, 0.05]}>
            <boxGeometry args={[0.16, 0.26, 0.1]} />
            <meshStandardMaterial
              color="#dff6ff"
              emissive={CYAN}
              emissiveIntensity={emphasis ? 1.4 : 0.8}
            />
          </mesh>
        )}

        {/* knee joint */}
        <mesh position={[0, -1.05, 0]}>
          <sphereGeometry args={[0.2, 20, 20]} />
          <meshStandardMaterial
            color={colour}
            emissive={colour}
            emissiveIntensity={ghost ? 0.1 : 0.9}
            transparent
            opacity={opacity}
          />
        </mesh>

        {/* shin, hinged at the knee */}
        <group ref={shin} position={[0, -1.05, 0]}>
          <mesh position={[0, -0.52, 0]} geometry={segment(0.84)}>
            <meshStandardMaterial
              color={colour}
              transparent
              opacity={opacity * (ghost ? 1 : 0.9)}
              roughness={0.35}
              metalness={0.25}
              emissive={colour}
              emissiveIntensity={ghost ? 0.05 : emphasis ? 0.45 : 0.22}
              depthWrite={!ghost}
            />
          </mesh>
          {!ghost && (
            <mesh position={[0.22, -0.42, 0.05]}>
              <boxGeometry args={[0.16, 0.26, 0.1]} />
              <meshStandardMaterial
                color="#dff6ff"
                emissive={CYAN}
                emissiveIntensity={emphasis ? 1.4 : 0.8}
              />
            </mesh>
          )}
          {/* foot */}
          <mesh position={[0, -1.0, 0.12]}>
            <boxGeometry args={[0.3, 0.1, 0.44]} />
            <meshStandardMaterial
              color={colour}
              transparent
              opacity={opacity * 0.8}
              emissive={colour}
              emissiveIntensity={ghost ? 0.05 : 0.2}
            />
          </mesh>
        </group>
      </group>
    </group>
  );
}

/** A slow ring under the limbs; its brightness reads as confidence. */
function ConfidenceHalo({ confidence }: { confidence: number }) {
  const ring = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (!ring.current) return;
    ring.current.rotation.z = state.clock.elapsedTime * 0.12;
  });
  return (
    <mesh ref={ring} position={[0, -1.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[1.5, 1.62, 64]} />
      <meshBasicMaterial
        color={confidence > 0.8 ? TEAL : confidence > 0.5 ? CYAN : "#ecb87d"}
        transparent
        opacity={0.18 + confidence * 0.4}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

function Scene({ input, mode }: { input: CoreInput; mode: MovementCoreMode }) {
  const operatedLeft = input.operated === "LEFT";
  const operatedRight = input.operated === "RIGHT";
  const active = input.active ?? mode === "live";

  return (
    <>
      <ambientLight intensity={0.55} />
      <directionalLight position={[3, 5, 4]} intensity={1.1} />
      <pointLight position={[-3, 1, 3]} intensity={0.6} color={VIOLET} />

      {/* baseline behind the current limbs, so the change is spatial */}
      {mode === "compare" && (
        <group position={[0, 0, -0.7]}>
          <Limb x={-0.75} flex={input.baselineLeft ?? 0} colour={GHOST} ghost phase={0} active={active} />
          <Limb x={0.75} flex={input.baselineRight ?? 0} colour={GHOST} ghost phase={0.5} active={active} />
        </group>
      )}

      <Limb x={-0.75} flex={input.left} colour={CYAN} emphasis={operatedLeft} phase={0} active={active} />
      <Limb x={0.75} flex={input.right} colour={VIOLET} emphasis={operatedRight} phase={0.5} active={active} />

      <ConfidenceHalo confidence={input.confidence ?? 0.8} />
    </>
  );
}

/**
 * Lite equivalent.
 *
 * Not a blank fallback: the same two limbs, the same hinge, the same operated
 * highlight — drawn with SVG so the meaning survives when WebGL does not.
 */
function LiteCore({ input }: { input: CoreInput }) {
  const limb = (cx: number, flex: number, colour: string, emphasis: boolean) => {
    const rad = (flex * Math.PI) / 180;
    const kneeY = 150;
    const ankleX = cx + Math.sin(rad) * 78;
    const ankleY = kneeY + Math.cos(rad) * 78;
    return (
      <g key={cx} opacity={emphasis ? 1 : 0.85}>
        <line x1={cx} y1={60} x2={cx} y2={kneeY} stroke={colour}
              strokeWidth={emphasis ? 13 : 11} strokeLinecap="round" opacity={0.85} />
        <line x1={cx} y1={kneeY} x2={ankleX} y2={ankleY} stroke={colour}
              strokeWidth={emphasis ? 13 : 11} strokeLinecap="round" opacity={0.85} />
        <circle cx={cx} cy={kneeY} r={9} fill={colour} />
        {/* sensor nodes */}
        <rect x={cx + 8} y={96} width={9} height={16} rx={2.5} fill="#dff6ff" stroke={colour} />
        <rect x={cx + Math.sin(rad) * 34 + 8} y={kneeY + Math.cos(rad) * 34 - 8}
              width={9} height={16} rx={2.5} fill="#dff6ff" stroke={colour} />
        <text x={cx} y={40} textAnchor="middle" className="mc-lite-label">
          {Math.round(flex)}°
        </text>
      </g>
    );
  };
  return (
    <svg viewBox="0 0 320 280" className="mc-lite" role="img"
         aria-label={`Estimated peak flexion: left ${Math.round(input.left)} degrees, right ${Math.round(input.right)} degrees`}>
      <ellipse cx="160" cy="248" rx="120" ry="16" className="mc-lite-floor" />
      {limb(110, input.left, CYAN, input.operated === "LEFT")}
      {limb(210, input.right, VIOLET, input.operated === "RIGHT")}
    </svg>
  );
}

export function MovementCore({
  input,
  mode = "overview",
  height = 320,
}: {
  input: CoreInput;
  mode?: MovementCoreMode;
  height?: number;
}) {
  const { glActive, reducedMotion } = useSceneStatus();

  // Reduced motion keeps the 3D but stops the cycle, so the shape is still
  // readable without anything moving.
  const resolved = useMemo<CoreInput>(
    () => ({ ...input, active: reducedMotion ? false : input.active }),
    [input, reducedMotion],
  );

  if (!glActive) {
    return (
      <div className="mc-wrap" style={{ height }}>
        <LiteCore input={resolved} />
      </div>
    );
  }

  return (
    <div className="mc-wrap" style={{ height }}>
      <Canvas
        camera={{ position: [0, 0.2, 5.2], fov: 42 }}
        dpr={[1, 1.8]}
        gl={{ antialias: true, alpha: true }}
      >
        <Suspense fallback={null}>
          <Scene input={resolved} mode={mode} />
        </Suspense>
      </Canvas>
    </div>
  );
}
