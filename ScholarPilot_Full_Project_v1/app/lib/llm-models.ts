export const USER_LLM_MODELS = [
  "deepseek-v4-pro",
  "deepseek-v4-flash",
] as const;

export type UserLlmModel = (typeof USER_LLM_MODELS)[number];

export const DEFAULT_USER_LLM_MODEL: UserLlmModel = "deepseek-v4-pro";

export function isUserLlmModel(value: string): value is UserLlmModel {
  return USER_LLM_MODELS.some((model) => model === value);
}
