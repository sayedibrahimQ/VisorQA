import React from "react";

export const REPO_URL = "https://github.com/sayedibrahimQ/VisorQA";
export const MISSION_CONTROL_URL = "/runs/run-demo-42";
export const CLI_CMD = "npx visorqa init";
export const FOCUS =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas";

export function SectionHeading({
  kicker,
  title,
  body,
}: {
  kicker?: string;
  title: string;
  body?: string;
}) {
  return (
    <div className="max-w-2xl">
      {kicker && (
        <p className="font-mono text-xs text-cyan-300">{kicker}</p>
      )}
      <h2 className="mt-2 font-display text-3xl font-semibold tracking-tight text-text-primary">
        {title}
      </h2>
      {body && (
        <p className="mt-3 text-base leading-relaxed text-text-secondary">
          {body}
        </p>
      )}
    </div>
  );
}
