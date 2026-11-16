"use client";
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/languages/definitions/python/register.js";
import { useEffect, useState } from "react";
loader.config({ monaco });
export default function PythonEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [plain, setPlain] = useState(false);
  useEffect(() => {
    (
      window as typeof window & { MonacoEnvironment?: unknown }
    ).MonacoEnvironment = {
      getWorker: () =>
        new Worker(
          new URL("monaco-editor/editor/editor.worker.js", import.meta.url),
          { type: "module" },
        ),
    };
  }, []);
  return (
    <div className="editor-content">
      <button className="editor-mode" onClick={() => setPlain(!plain)}>
        {plain ? "Use Monaco editor" : "Use accessible text editor"}
      </button>
      {plain ? (
        <textarea
          className="plain-editor"
          aria-label="Python source code"
          spellCheck={false}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <Editor
          language="python"
          theme="vs-dark"
          value={value}
          onChange={(v) => onChange(v || "")}
          height="100%"
          loading={
            <div className="editor-loading">
              Loading Python editor… Use the text editor if needed.
            </div>
          }
          options={{
            ariaLabel: "Python source code",
            minimap: { enabled: false },
            fontSize: 14,
            lineHeight: 25,
            fontFamily: "'SFMono-Regular', Consolas, monospace",
            padding: { top: 22 },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 4,
            wordWrap: "on",
            renderLineHighlight: "gutter",
            accessibilitySupport: "on",
            bracketPairColorization: { enabled: true },
          }}
        />
      )}
    </div>
  );
}
