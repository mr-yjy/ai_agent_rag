"use client";

import { useState } from "react";
import {
  USER_LLM_MODELS,
  type UserLlmModel,
} from "../lib/llm-models";

interface Props {
  language: "zh" | "en";
  apiKey: string;
  model: UserLlmModel;
  onClose: () => void;
  onSave: (apiKey: string, model: UserLlmModel) => void;
  onClear: () => void;
}

function validApiKey(value: string) {
  const normalized = value.trim();
  return (
    normalized.length >= 16
    && normalized.length <= 512
    && !/\s/.test(normalized)
  );
}

export default function ApiSettingsDrawer({
  language,
  apiKey,
  model,
  onClose,
  onSave,
  onClear,
}: Props) {
  const [draft, setDraft] = useState(apiKey);
  const [draftModel, setDraftModel] = useState<UserLlmModel>(model);
  const [revealed, setRevealed] = useState(false);
  const [error, setError] = useState("");
  const english = language === "en";

  function save() {
    const normalized = draft.trim();
    if (!validApiKey(normalized)) {
      setError(
        english
          ? "Enter a valid DeepSeek API key without spaces."
          : "请输入不含空格的有效 DeepSeek API Key。",
      );
      return;
    }
    onSave(normalized, draftModel);
  }

  return (
    <div
      className="drawer-overlay settings-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className="settings-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        aria-describedby="settings-description"
      >
        <header>
          <div>
            <span>SETTINGS / BYOK</span>
            <h2 id="settings-title">
              {english ? "DeepSeek connection" : "DeepSeek 连接"}
            </h2>
            <p id="settings-description">
              {english
                ? "Use your own key for query analysis and evidence ranking."
                : "使用你自己的密钥完成查询分析与证据排序。"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={english ? "Close settings" : "关闭设置"}
          >
            ×
          </button>
        </header>

        <form
          className="settings-content"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <div className={`key-status ${apiKey ? "active" : ""}`}>
            <i aria-hidden="true" />
            <div>
              <strong>
                {apiKey
                  ? english
                    ? "Using your API key"
                    : "正在使用你的 API Key"
                  : english
                    ? "Personal API key required"
                    : "需要添加个人 API Key"}
              </strong>
              <small>
                {apiKey
                  ? `DeepSeek · ${model}`
                  : english
                    ? "Search is unavailable until configured"
                    : "配置前无法发起检索"}
              </small>
            </div>
          </div>

          <fieldset className="settings-models">
            <legend>{english ? "Personal model" : "个人模型"}</legend>
            <div>
              {USER_LLM_MODELS.map((modelOption) => {
                const flash = modelOption === "deepseek-v4-flash";
                return (
                  <label
                    className={draftModel === modelOption ? "selected" : ""}
                    key={modelOption}
                  >
                    <input
                      type="radio"
                      name="deepseek-model"
                      value={modelOption}
                      checked={draftModel === modelOption}
                      onChange={() => setDraftModel(modelOption)}
                    />
                    <span>
                      <strong>{flash ? "V4 Flash" : "V4 Pro"}</strong>
                      <small>
                        {flash
                          ? english
                            ? "Faster retrieval cycles"
                            : "更快的检索响应"
                          : english
                            ? "Deeper evidence analysis"
                            : "更深入的证据分析"}
                      </small>
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <label className="api-key-field" htmlFor="deepseek-api-key">
            <span>DeepSeek API Key</span>
            <div>
              <input
                id="deepseek-api-key"
                type={revealed ? "text" : "password"}
                value={draft}
                autoFocus
                autoCapitalize="none"
                autoComplete="new-password"
                spellCheck={false}
                aria-invalid={Boolean(error)}
                aria-describedby={
                  error ? "api-key-error key-security-note" : "key-security-note"
                }
                placeholder="sk-••••••••••••••••••••••••"
                onChange={(event) => {
                  setDraft(event.target.value);
                  setError("");
                }}
              />
              <button
                type="button"
                onClick={() => setRevealed((current) => !current)}
                aria-label={
                  revealed
                    ? english
                      ? "Hide API key"
                      : "隐藏 API Key"
                    : english
                      ? "Show API key"
                      : "显示 API Key"
                }
              >
                {revealed
                  ? english
                    ? "Hide"
                    : "隐藏"
                  : english
                    ? "Show"
                    : "显示"}
              </button>
            </div>
          </label>

          {error && (
            <p className="settings-error" id="api-key-error" role="alert">
              {error}
            </p>
          )}

          <div className="key-security-note" id="key-security-note">
            <strong>
              {english ? "Stored for this tab only" : "仅保存在当前标签页"}
            </strong>
            <p>
              {english
                ? "The key stays in session storage and is forwarded only with search requests. It is not written to the server configuration or returned in responses."
                : "密钥仅保存在当前标签页的会话存储中，并只随检索请求转发；不会写入服务端配置，也不会出现在响应中。"}
            </p>
          </div>

          <div className="settings-actions">
            <button
              type="button"
              className="subtle-button"
              disabled={!apiKey}
              onClick={() => {
                onClear();
                setDraft("");
                setError("");
              }}
            >
              {english ? "Remove personal key" : "移除个人 Key"}
            </button>
            <button
              type="submit"
              className="primary-small-button"
              disabled={!validApiKey(draft)}
            >
              {english ? "Save for this session" : "保存到当前会话"}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}
