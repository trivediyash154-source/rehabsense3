import { z } from "zod";

export const contactRoles = [
  "Patient",
  "Physiotherapist",
  "Researcher",
  "Student",
  "Other",
] as const;

export const contactReasons = [
  "Demonstration",
  "Research",
  "Clinical discussion",
  "General enquiry",
] as const;

export const contactSchema = z.object({
  name: z.string().trim().min(2, "Enter your full name.").max(100),
  email: z.string().trim().email("Enter a valid email address.").max(254),
  phone: z
    .string()
    .trim()
    .max(30)
    .refine(
      (value) => !value || /^[+\d().\s-]{7,30}$/.test(value),
      "Enter a valid contact number.",
    ),
  organization: z.string().trim().min(2, "Enter your organization.").max(160),
  role: z.enum(contactRoles, { errorMap: () => ({ message: "Select your role." }) }),
  reason: z.enum(contactReasons, { errorMap: () => ({ message: "Select a reason." }) }),
  message: z
    .string()
    .trim()
    .min(20, "Please include at least 20 characters.")
    .max(3000),
  consent: z.literal(true, {
    errorMap: () => ({ message: "Your consent is required to send this message." }),
  }),
  // Honeypot: must stay empty. Never forwarded to the delivery endpoint.
  website: z.string().max(0, "Unable to submit this request."),
});

export type ContactValues = z.infer<typeof contactSchema>;

export type AuthMode =
  | "login"
  | "signup"
  | "forgot-password"
  | "verify-phone"
  | "verify-email";

export const authRoles = ["Patient", "Physiotherapist", "Researcher", "Other"] as const;

/** Dial codes offered in the phone field. Kept small and explicit. */
export const dialCodes = [
  { code: "+91", label: "India (+91)" },
  { code: "+1", label: "United States / Canada (+1)" },
  { code: "+44", label: "United Kingdom (+44)" },
  { code: "+61", label: "Australia (+61)" },
  { code: "+49", label: "Germany (+49)" },
  { code: "+971", label: "United Arab Emirates (+971)" },
  { code: "+65", label: "Singapore (+65)" },
] as const;

export const authDefaults = {
  name: "",
  email: "",
  dialCode: "+91" as string,
  phone: "",
  password: "",
  confirmPassword: "",
  role: "",
  code: "",
  consent: false,
};

export type AuthValues = typeof authDefaults;

/** National number only — the dial code is validated separately. */
const nationalNumber = /^[\d\s().-]{6,15}$/;

export function makeAuthSchema(mode: AuthMode) {
  return z
    .object({
      name: z.string(),
      email: z.string(),
      dialCode: z.string(),
      phone: z.string(),
      password: z.string(),
      confirmPassword: z.string(),
      role: z.string(),
      code: z.string(),
      consent: z.boolean(),
    })
    .superRefine((data, context) => {
      const error = (path: keyof AuthValues, message: string) =>
        context.addIssue({ code: "custom", path: [path], message });

      const digits = data.phone.replace(/\D/g, "");

      if (["login", "signup", "forgot-password", "verify-email"].includes(mode)) {
        if (!z.string().email().safeParse(data.email.trim()).success) {
          error("email", "Enter a valid email address.");
        }
      }

      if (mode === "signup") {
        if (data.name.trim().length < 2) error("name", "Enter your full name.");
        // Optional: nothing verifies or uses a phone number in this prototype,
        // so it must not stand between a person and an account. Checked only
        // when one is entered.
        if (data.phone.trim()) {
          if (!nationalNumber.test(data.phone.trim()) || digits.length < 6) {
            error("phone", "Enter a valid phone number, or leave it empty.");
          }
          if (!dialCodes.some((entry) => entry.code === data.dialCode)) {
            error("dialCode", "Select a country code.");
          }
        }
        if (data.password.length < 12) error("password", "Use at least 12 characters.");
        if (data.password.length > 200) error("password", "Use fewer than 200 characters.");
        if (data.password !== data.confirmPassword) {
          error("confirmPassword", "Passwords do not match.");
        }
        if (!(authRoles as readonly string[]).includes(data.role)) {
          error("role", "Select a role.");
        }
        if (!data.consent) error("consent", "Review and accept the prototype terms.");
      }

      if (mode === "login" && !data.password) error("password", "Enter your password.");

      if (mode === "verify-phone") {
        if (!nationalNumber.test(data.phone.trim()) || digits.length < 6) {
          error("phone", "Enter a valid phone number.");
        }
      }

      if (mode.startsWith("verify") && !/^\d{6}$/.test(data.code)) {
        error("code", "Enter the six-digit verification code.");
      }
    });
}

/** 0–4 heuristic used by the strength meter. Never sent anywhere. */
export function passwordStrength(password: string) {
  if (!password) return 0;
  return (
    Number(password.length >= 8) +
    Number(password.length >= 12) +
    Number(/[a-z]/.test(password) && /[A-Z]/.test(password)) +
    Number(/[\d\W]/.test(password))
  );
}

export const strengthLabels = ["Weak", "Weak", "Fair", "Good", "Stronger"] as const;
