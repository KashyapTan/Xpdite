import { useState, useEffect } from "react";
import { api } from "../../services/api";
import { CheckIcon } from "../icons/AppIcons";
import "../../CSS/SettingsSystemPrompt.css";

export default function SettingsSystemPrompt() {
    const [template, setTemplate] = useState("");
    const [isCustom, setIsCustom] = useState(false);
    const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

    useEffect(() => {
        api.getSystemPrompt().then((data: { template: string, is_custom: boolean }) => {
            setTemplate(data.template);
            setIsCustom(data.is_custom);
        });
    }, []);

    const handleSave = async () => {
        setStatus("saving");
        try {
            await api.setSystemPrompt(template);
            setIsCustom(true);
            setStatus("saved");
            setTimeout(() => setStatus("idle"), 2000);
        } catch {
            setStatus("error");
        }
    };

    const handleReset = async () => {
        await api.setSystemPrompt("");          // empty string clears the custom value
        const { template: def } = await api.getSystemPrompt();
        setTemplate(def);
        setIsCustom(false);
        setStatus("idle");
    };

    return (
        <div className="settings-system-prompt">
            <div className="settings-system-prompt-top">
                <div className="settings-system-prompt-header-text">
                    <h2>Customize System Prompt</h2>
                    <p>
                        Use <code>{"current_datetime"}</code>, <code>{"os_info"}</code>,
                        <code>{"skills_block"}</code>, <code>{"memory_block"}</code>, and <code>{"user_profile_block"}</code> as placeholders exactly as written.
                        Older custom templates that omit the memory or profile placeholders still get those sections auto-appended at runtime.
                        {/* {isCustom && <span className="custom-badge">Custom</span>} */}
                    </p>
                </div>
                <div className="settings-actions">
                    <button onClick={handleReset} className="secondary-button" disabled={status === "saving"}>
                        Reset to Default
                    </button>
                    <button onClick={handleSave} className="primary-button" disabled={status === "saving"}>
                        {status === "saving" ? "Saving…" : status === "saved" ? (
                            <>
                                <CheckIcon size={14} className="primary-button-icon" />
                                Saved
                            </>
                        ) : "Save"}
                    </button>

                </div>
            </div>
            {status === "error" && <span className="error-text">Save failed.</span>}
            {isCustom && <span className="custom-badge" title="You are using a custom prompt">Custom</span>}
            <textarea
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                spellCheck={false}
                className="system-prompt-textarea"
            />
        </div>
    );
}
