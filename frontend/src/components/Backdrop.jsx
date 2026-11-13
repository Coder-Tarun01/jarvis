import { useEffect, useRef } from "react";

import { useReducedMotion } from "../hooks/useHudEnvironment.js";

/**
 * Layered cinematic backdrop: perspective grid, drifting particles, scanlines,
 * grain and a vignette. Everything except the particle canvas is static CSS, and
 * the canvas pauses when the tab is hidden or when reduced motion is requested.
 */
export default function Backdrop() {
  const canvasRef = useRef(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return undefined;

    let width = 0;
    let height = 0;
    let frame = 0;
    let visible = !document.hidden;
    let particles = [];

    const paint = (time) => {
      context.clearRect(0, 0, width, height);
      for (let index = 0; index < particles.length; index += 1) {
        const particle = particles[index];
        particle.x += particle.vx;
        particle.y += particle.vy;
        if (particle.y < -6) {
          particle.y = height + 6;
          particle.x = Math.random() * width;
        }
        if (particle.x < -6) particle.x = width + 6;
        else if (particle.x > width + 6) particle.x = -6;

        const twinkle = 0.7 + 0.3 * Math.sin(time * 0.0007 + particle.phase);
        const alpha = particle.alpha * twinkle;
        context.beginPath();
        context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
        context.fillStyle =
          particle.tint === "violet"
            ? `rgba(167, 139, 250, ${alpha})`
            : `rgba(103, 232, 249, ${alpha})`;
        context.fill();
      }
    };

    const loop = (time) => {
      paint(time);
      frame = requestAnimationFrame(loop);
    };

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);

      const count = Math.max(28, Math.min(80, Math.round((width * height) / 30000)));
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: Math.random() * 1.2 + 0.25,
        vx: (Math.random() - 0.5) * 0.05,
        vy: -(Math.random() * 0.1 + 0.015),
        alpha: Math.random() * 0.42 + 0.12,
        phase: Math.random() * Math.PI * 2,
        tint: Math.random() > 0.78 ? "violet" : "cyan",
      }));

      if (reduced) paint(0);
    };

    const onVisibility = () => {
      visible = !document.hidden;
      if (reduced) return;
      if (visible && !frame) frame = requestAnimationFrame(loop);
      if (!visible && frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    };

    resize();
    if (!reduced) frame = requestAnimationFrame(loop);

    let resizeFrame = 0;
    const onResize = () => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(resize);
    };

    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      if (frame) cancelAnimationFrame(frame);
      cancelAnimationFrame(resizeFrame);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [reduced]);

  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {/* perspective floor */}
      <div className="absolute inset-x-0 bottom-0 h-[46vh] [perspective:640px]">
        <div className="grid-floor absolute inset-0 origin-bottom opacity-70 [transform:rotateX(74deg)_scale(1.6)]" />
      </div>

      {/* upper grid, very faint */}
      <div className="grid-floor absolute inset-0 opacity-25" />

      {/* drifting particles */}
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full opacity-80" />

      {/* horizontal scanlines + film grain */}
      <div className="scanlines absolute inset-0" />
      <div className="noise absolute inset-0" />

      {/* moving scan sweep */}
      <div className="absolute inset-0 overflow-hidden opacity-60">
        <div className="scan-band" />
      </div>

      {/* vignette */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_45%,transparent_30%,rgba(2,4,10,0.55)_78%,rgba(2,4,10,0.92)_100%)]" />
    </div>
  );
}
