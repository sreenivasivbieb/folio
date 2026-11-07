/** The schema is user-editable (FR-4). Every save creates a new version; claims record theirs. */
import { useEffect, useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { useAction, useSchema } from "@/api/queries";
import { Modal } from "@/components/Modal";
import { ui } from "@/state/selection";

export function SchemaEditor() {
  const { client } = useApi();
  const { data } = useSchema();
  const [text, setText] = useState("");
  useEffect(() => setText(data?.yaml ?? ""), [data?.yaml]);
  const save = useAction(async (yaml: string) => unwrap(await client.PUT("/api/schema", { body: { yaml } })), "Schema saved as a new version");
  const close = () => ui.set({ modal: "none" });

  return (
    <Modal
      title={<>Schema <span className="badge">v{data?.version}</span></>}
      onClose={close}
      footer={
        <>
          <span className="small muted" style={{ marginRight: "auto" }}>Entity types, attributes (with spoken phrases) and relations. Changes apply to the next extraction.</span>
          <button type="button" className="btn" onClick={close}>Close</button>
          <button type="button" className="btn primary" onClick={() => save.mutate(text, { onSuccess: close })}>Save new version</button>
        </>
      }
    >
      <textarea className="input schema" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
    </Modal>
  );
}
