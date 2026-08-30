"use client";

import { cn } from "@/lib/utils";
import React, { useEffect, useRef } from "react";
import * as THREE from "three";

type DottedSurfaceProps = Omit<React.ComponentProps<"div">, "ref"> & {
  size?: number;
  opacity?: number;
};

// Adapted from the original DottedSurface component: removed the next-themes
// dependency (this app has no light/dark toggle — it's always dark, matching
// the rest of the Primer identity) and tinted the particle color to the gold
// accent instead of the original black/white swap.
export function DottedSurface({ className, size = 6, opacity = 0.55, ...props }: DottedSurfaceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    animationId: number;
    count: number;
  } | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const SEPARATION = 150;
    const AMOUNTX = 40;
    const AMOUNTY = 60;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0f151d, 2000, 10000);

    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 1, 10000);
    camera.position.set(0, 355, 1220);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x0f151d, 0);

    containerRef.current.appendChild(renderer.domElement);

    const positions: number[] = [];
    const colors: number[] = [];
    // Gold (#CC9A4E) in 0-255 range, matching the design system's accent
    const GOLD = { r: 204, g: 154, b: 78 };

    const geometry = new THREE.BufferGeometry();

    for (let ix = 0; ix < AMOUNTX; ix++) {
      for (let iy = 0; iy < AMOUNTY; iy++) {
        const x = ix * SEPARATION - (AMOUNTX * SEPARATION) / 2;
        const z = iy * SEPARATION - (AMOUNTY * SEPARATION) / 2;
        positions.push(x, 0, z);
        colors.push(GOLD.r, GOLD.g, GOLD.b);
      }
    }

    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size,
      vertexColors: true,
      transparent: true,
      opacity,
      sizeAttenuation: true,
    });

    const points = new THREE.Points(geometry, material);
    scene.add(points);

    let count = 0;
    let animationId: number;

    const renderStatic = () => {
      renderer.render(scene, camera);
    };

    const animate = () => {
      animationId = requestAnimationFrame(animate);
      const positionAttribute = geometry.attributes.position;
      const pos = positionAttribute.array as Float32Array;

      let i = 0;
      for (let ix = 0; ix < AMOUNTX; ix++) {
        for (let iy = 0; iy < AMOUNTY; iy++) {
          const index = i * 3;
          pos[index + 1] = Math.sin((ix + count) * 0.3) * 50 + Math.sin((iy + count) * 0.5) * 50;
          i++;
        }
      }
      positionAttribute.needsUpdate = true;
      renderer.render(scene, camera);
      count += 0.06; // slower drift than the original — ambient, not busy
    };

    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };

    window.addEventListener("resize", handleResize);

    if (prefersReducedMotion) {
      renderStatic();
    } else {
      animate();
    }

    sceneRef.current = { scene, camera, renderer, animationId: 0, count };

    return () => {
      window.removeEventListener("resize", handleResize);
      if (sceneRef.current) {
        cancelAnimationFrame(animationId);
        scene.traverse((object) => {
          if (object instanceof THREE.Points) {
            object.geometry.dispose();
            (object.material as THREE.Material).dispose();
          }
        });
        renderer.dispose();
        if (containerRef.current && renderer.domElement) {
          containerRef.current.removeChild(renderer.domElement);
        }
      }
    };
  }, [size, opacity]);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className={cn("pointer-events-none fixed inset-0 -z-10", className)}
      {...props}
    />
  );
}

export default DottedSurface;
