export const METHODS = [
  { id: "email", label: "Email" },
  { id: "google", label: "Google" },
] as const;

export type Method = (typeof METHODS)[number]["id"];
