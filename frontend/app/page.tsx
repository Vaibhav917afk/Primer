"use client";

import { motion } from "framer-motion";
import { DottedSurface } from "@/components/ui/dotted-surface";
import { UploadForm } from "@/components/upload-form";
import { JobList } from "@/components/job-list";

export default function HomePage() {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center px-6 py-24">
      <DottedSurface />

      {/* radial fade so the particle field doesn't fight the content for attention */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 60% 50% at 50% 45%, rgba(15,21,29,0.4) 0%, rgba(15,21,29,0.92) 70%, #0F151D 100%)",
        }}
      />

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        className="mb-10 flex flex-col items-center text-center"
      >
        <span className="mb-4 font-mono text-xs uppercase tracking-[0.2em] text-gold">primer</span>
        <h1 className="font-display text-4xl font-semibold italic text-cream sm:text-5xl">
          Drop in a conversation.
        </h1>
        <p className="mt-4 max-w-md font-sans text-base text-cream-dim">
          A call, a video, a chat export — Primer verifies its own understanding before
          trusting it, and gets you ready for the next one.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.15, ease: "easeOut" }}
        className="flex w-full flex-col items-center"
      >
        <UploadForm />
        <JobList />
      </motion.div>
    </main>
  );
}
