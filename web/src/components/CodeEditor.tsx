import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { json } from "@codemirror/lang-json";
import CodeMirror from "@uiw/react-codemirror";

type Lang = "json" | "html" | "css";

const EXT = {
  json: [json()],
  html: [html()],
  css: [css()],
};

export function CodeEditor({
  value,
  onChange,
  lang,
  height = "200px",
}: {
  value: string;
  onChange: (v: string) => void;
  lang: Lang;
  height?: string;
}) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}>
      <CodeMirror
        value={value}
        height={height}
        theme="dark"
        extensions={EXT[lang]}
        onChange={onChange}
        basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
      />
    </div>
  );
}
