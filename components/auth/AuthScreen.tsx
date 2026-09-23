"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowLeft,
  ArrowUpRight,
  Eye,
  EyeOff,
  LoaderCircle,
  Check,
  Phone,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import { ThemeToggle } from "@/components/ui/Providers";
import { Modal } from "@/components/ui/Primitives";
import { AuthStage } from "@/components/auth/AuthStage";
import { LiteToggle } from "@/components/three/SceneContext";
import {
  authDefaults,
  authRoles,
  dialCodes,
  makeAuthSchema,
  passwordStrength,
  strengthLabels,
  type AuthMode,
  type AuthValues,
} from "@/lib/validations";
import {
  AuthError,
  homeForRole,
  signIn,
  signUp,
  type UserRole,
} from "@/lib/auth";
import { useAuth } from "@/components/auth/AuthProvider";
import { codeAllowlist, track } from "@/lib/analytics";

/**
 * The roles a person may pick for themselves.
 *
 * The backend refuses ADMIN at signup, and clinical access is gated on an
 * active patient assignment rather than on the chosen role, so choosing
 * "Physiotherapist" grants no access to anyone else's data on its own.
 */
const ROLE_VALUES: Record<string, UserRole> = {
  Patient: "PATIENT",
  Physiotherapist: "PHYSIOTHERAPIST",
  Researcher: "TECHNICIAN",
  // Least privilege for anything unrecognised.
  Other: "PATIENT",
};

const copy: Record<AuthMode, { title: string; description: string; submit: string }> = {
  login: {
    title: "Return to your movement story.",
    description: "A clearer perspective is waiting where you left it.",
    submit: "Sign in",
  },
  signup: {
    title: "Begin with a clearer perspective.",
    description: "Create a place for the work your body is doing.",
    submit: "Create account",
  },
  "forgot-password": {
    title: "Find your way back.",
    description: "Give us the email on the account and we'll help reconnect it.",
    submit: "Send reset link",
  },
  "verify-phone": {
    title: "Confirm the connection.",
    description: "Enter your number and the six-digit code to continue.",
    submit: "Verify phone number",
  },
  "verify-email": {
    title: "One more connection.",
    description: "Enter the six-digit code we would send to your inbox.",
    submit: "Verify email",
  },
};

/**
 * Six separate inputs with roving focus, paste support and backspace
 * navigation. The value is a plain string; a space marks an empty slot so
 * positions stay stable while the user edits in the middle.
 */
function OtpInput({
  value,
  onChange,
  error,
}: {
  value: string;
  onChange: (value: string) => void;
  error?: string;
}) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    // Land the caret in the first empty slot when the step appears.
    const first = Math.min(value.replace(/\s/g, "").length, 5);
    refs.current[first]?.focus();
    // Only on mount: re-focusing on every keystroke would fight the user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setDigit = (index: number, digit: string) => {
    const next = value.padEnd(6, " ").split("");
    next[index] = digit || " ";
    onChange(next.join("").replace(/\s+$/, ""));
  };

  return (
    <fieldset className="otp-field">
      <legend>Verification code</legend>
      <div className="otp-inputs">
        {Array.from({ length: 6 }, (_, i) => (
          <input
            key={i}
            ref={(element) => {
              refs.current[i] = element;
            }}
            aria-label={`Verification code digit ${i + 1} of 6`}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "otp-error" : undefined}
            inputMode="numeric"
            pattern="\d*"
            autoComplete={i === 0 ? "one-time-code" : "off"}
            maxLength={1}
            value={value[i] === " " ? "" : (value[i] ?? "")}
            onChange={(event) => {
              const digit = event.target.value.replace(/\D/g, "").slice(-1);
              setDigit(i, digit);
              if (digit) refs.current[Math.min(5, i + 1)]?.focus();
            }}
            onKeyDown={(event) => {
              if (event.key === "Backspace" && !value[i]?.trim()) {
                event.preventDefault();
                setDigit(Math.max(0, i - 1), "");
                refs.current[Math.max(0, i - 1)]?.focus();
              }
              if (event.key === "ArrowLeft") refs.current[Math.max(0, i - 1)]?.focus();
              if (event.key === "ArrowRight") refs.current[Math.min(5, i + 1)]?.focus();
            }}
            onPaste={(event) => {
              event.preventDefault();
              const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
              if (!pasted) return;
              onChange(pasted);
              refs.current[Math.min(5, pasted.length)]?.focus();
            }}
          />
        ))}
      </div>
      <span id="otp-error" className="field-error" role={error ? "alert" : undefined}>
        {error}
      </span>
    </fieldset>
  );
}

/** Brand glyphs drawn inline: no third-party script or remote asset. */
function GoogleMark() {
  return (
    <span className="provider-mark provider-mark-google" aria-hidden="true">
      <svg viewBox="0 0 18 18" width="15" height="15">
        <path fill="#EA4335" d="M9 3.48c1.69 0 2.83.73 3.48 1.34l2.54-2.48C13.46.89 11.43 0 9 0 5.48 0 2.44 2.02.96 4.96l2.91 2.26C4.6 5.05 6.62 3.48 9 3.48z" />
        <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72l2.84 2.2c1.66-1.53 2.76-3.79 2.76-6.56z" />
        <path fill="#FBBC05" d="M3.88 10.78A5.54 5.54 0 0 1 3.58 9c0-.62.11-1.22.29-1.78L.96 4.96A8.99 8.99 0 0 0 0 9c0 1.45.35 2.82.96 4.04l2.92-2.26z" />
        <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.84-2.2c-.76.53-1.78.9-3.12.9-2.38 0-4.4-1.57-5.13-3.74L.96 13.04C2.44 15.98 5.48 18 9 18z" />
      </svg>
    </span>
  );
}

function FacebookMark() {
  return (
    <span className="provider-mark provider-mark-facebook" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="15" height="15" fill="#1877F2">
        <path d="M24 12.07C24 5.4 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.05V9.41c0-3.02 1.79-4.69 4.53-4.69 1.31 0 2.68.24 2.68.24v2.96h-1.51c-1.49 0-1.96.93-1.96 1.89v2.26h3.33l-.53 3.49h-2.8V24C19.61 23.1 24 18.1 24 12.07z" />
      </svg>
    </span>
  );
}

export function AuthScreen({ mode }: { mode: AuthMode }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refresh } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState("");
  const [succeeded, setSucceeded] = useState(false);
  const [providerBusy, setProviderBusy] = useState<"google" | "facebook" | "resend" | null>(null);
  const [terms, setTerms] = useState(false);
  const [seconds, setSeconds] = useState(0);

  const isVerify = mode.startsWith("verify");
  const isSignup = mode === "signup";
  const isLogin = mode === "login";
  const isReset = mode === "forgot-password";

  const {
    register,
    watch,
    setValue,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<AuthValues>({
    resolver: zodResolver(makeAuthSchema(mode)),
    defaultValues: authDefaults,
    mode: "onBlur",
  });

  const password = watch("password") ?? "";
  const strength = passwordStrength(password);

  useEffect(() => {
    if (seconds <= 0) return;
    const timer = setTimeout(() => setSeconds(seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [seconds]);

  async function submit(values: AuthValues) {
    setNotice("");
    track(
      isSignup
        ? "signup_started"
        : isReset
          ? "password_reset_requested"
          : mode === "verify-phone"
            ? "phone_verification_started"
            : "login_started",
      { action: mode },
    );

    // Password reset and code verification have no delivery provider wired up,
    // so they still say so rather than implying a message was sent.
    if (!isLogin && !isSignup) {
      setNotice(
        "Message delivery is not configured in this prototype, so no email or code was sent.",
      );
      return;
    }

    try {
      const session = isSignup
        ? await signUp({
            name: values.name,
            email: values.email,
            password: values.password,
            phone: values.phone ? `${values.dialCode} ${values.phone}`.trim() : undefined,
            role: ROLE_VALUES[values.role] ?? "PATIENT",
          })
        : await signIn(values.email, values.password);

      track(isSignup ? "signup_succeeded" : "login_succeeded", { role: session.user.role });

      // Let the confirmation land before navigating; the cookie is already set,
      // so this is presentation only.
      setSucceeded(true);
      await refresh();

      const next = searchParams.get("next");
      const destination =
        next && next.startsWith("/") && !next.startsWith("//")
          ? next
          : homeForRole(session.user.role);

      setTimeout(() => {
        router.replace(destination);
        router.refresh();
      }, 550);
    } catch (error) {
      // Only allowlisted codes reach analytics; anything else is bucketed.
      const raw = error instanceof AuthError ? error.code : "ERROR";
      const code = (codeAllowlist as readonly string[]).includes(raw)
        ? (raw as (typeof codeAllowlist)[number])
        : "ERROR";
      // Field-level messages from the backend are more useful than a banner.
      if (error instanceof AuthError && error.fields.length > 0) {
        for (const detail of error.fields) {
          if (detail.field in authDefaults) {
            setError(detail.field as keyof AuthValues, { message: detail.message });
          }
        }
      }
      setNotice(
        error instanceof Error ? error.message : "Unable to continue. Please try again.",
      );
      track(isLogin ? "login_failed" : "error_occurred", { code });
    }
  }

  async function social(provider: "google" | "facebook") {
    setProviderBusy(provider);
    setNotice("");
    track("social_auth_started", { provider });
    // No reviewed OAuth adapter is configured, and pretending otherwise would
    // imply an account was created. Email and password sign-in is real.
    setNotice(
      `${provider === "google" ? "Google" : "Facebook"} sign-in is not configured in this prototype. Use email and password — that works.`,
    );
    setProviderBusy(null);
  }

  async function resend() {
    setProviderBusy("resend");
    setNotice("");
    track("verification_code_requested", { action: "resend" });
    // No delivery provider is configured. The cooldown deliberately does not
    // start, so the timer never implies a message that was never sent.
    setNotice("Message delivery is not configured in this prototype. No code was sent.");
    setProviderBusy(null);
  }

  const field = (
    name: "name" | "email" | "password" | "confirmPassword",
    label: string,
    type: string,
    autoComplete: string,
  ) => (
    <div className="field">
      <label htmlFor={`auth-${name}`}>{label}</label>
      <div className="input-wrap">
        <input
          id={`auth-${name}`}
          {...register(name)}
          type={type === "password" && showPassword ? "text" : type}
          autoComplete={autoComplete}
          aria-invalid={Boolean(errors[name])}
          aria-describedby={errors[name] ? `auth-${name}-error` : undefined}
        />
        {name === "password" && (
          <button
            type="button"
            className="password-toggle"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            aria-pressed={showPassword}
          >
            {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        )}
      </div>
      {errors[name] && (
        <span className="field-error" id={`auth-${name}-error`} role="alert">
          {errors[name]?.message}
        </span>
      )}
    </div>
  );

  const phoneField = (
    <div className="field">
      <label htmlFor="auth-phone">Phone number</label>
      <div className="phone-row">
        <div className="select-wrap dial-select">
          <label className="sr-only" htmlFor="auth-dialCode">
            Country calling code
          </label>
          <select id="auth-dialCode" {...register("dialCode")} aria-invalid={Boolean(errors.dialCode)}>
            {dialCodes.map((entry) => (
              <option key={entry.code} value={entry.code}>
                {entry.code}
              </option>
            ))}
          </select>
        </div>
        <input
          id="auth-phone"
          {...register("phone")}
          type="tel"
          inputMode="tel"
          autoComplete="tel-national"
          placeholder="98765 43210"
          aria-invalid={Boolean(errors.phone)}
          aria-describedby={errors.phone ? "auth-phone-error" : undefined}
        />
      </div>
      {(errors.phone || errors.dialCode) && (
        <span className="field-error" id="auth-phone-error" role="alert">
          {errors.phone?.message ?? errors.dialCode?.message}
        </span>
      )}
    </div>
  );

  return (
    <main className="auth-page" id="main">
      <div className="auth-top">
        <Logo />
        <ThemeToggle systemOption />
      </div>

      <div className="auth-layout">
        <AuthStage mode={mode} />

        <section className="auth-panel" aria-labelledby="auth-title">
          <div className="demo-mode-banner" role="note">
            <ShieldCheck size={16} aria-hidden="true" />
            <div>
              <strong>Research prototype — accounts are real</strong>
              <p>
                {isSignup || isLogin ? (
                  <>
                    Email and password sign-in creates a real account on the RehabSense backend:
                    your password is stored only as an Argon2id hash, and the session is held in a
                    cookie no script on this page can read. Social sign-in and email or SMS
                    delivery are not configured.
                  </>
                ) : (
                  <>
                    Email and SMS delivery is not configured in this prototype, so no message or
                    code is sent from this screen. Email and password sign-in works.
                  </>
                )}
              </p>
            </div>
          </div>

          <div className="auth-signature" aria-hidden="true">
            <i />
            <i />
            <span />
          </div>

          <h2 id="auth-title">{copy[mode].title}</h2>
          <p className="auth-description">{copy[mode].description}</p>

          {(isLogin || isSignup) && (
            <>
              <div className="social-buttons">
                <button
                  className="button button-outline"
                  type="button"
                  disabled={providerBusy !== null}
                  onClick={() => social("google")}
                >
                  {providerBusy === "google" ? (
                    <LoaderCircle className="spin" size={16} aria-hidden="true" />
                  ) : (
                    <GoogleMark />
                  )}
                  Continue with Google
                </button>
                <button
                  className="button button-outline"
                  type="button"
                  disabled={providerBusy !== null}
                  onClick={() => social("facebook")}
                >
                  {providerBusy === "facebook" ? (
                    <LoaderCircle className="spin" size={16} aria-hidden="true" />
                  ) : (
                    <FacebookMark />
                  )}
                  Continue with Facebook
                </button>
                <Link className="button button-outline provider-phone" href="/verify-phone">
                  <span className="provider-mark provider-mark-phone" aria-hidden="true">
                    <Phone size={15} />
                    <i className="phone-signal" />
                  </span>
                  Continue with phone number
                </Link>
              </div>
              <div className="form-divider" aria-hidden="true">
                <span className="divider-signal">
                  <svg viewBox="0 0 120 12" preserveAspectRatio="none">
                    <path d="M0 6 H62 l5 -5 l6 10 l6 -10 l5 5 H120" />
                  </svg>
                </span>
                <span className="divider-label">or continue with email</span>
                <span className="divider-signal divider-signal-flip">
                  <svg viewBox="0 0 120 12" preserveAspectRatio="none">
                    <path d="M0 6 H62 l5 -5 l6 10 l6 -10 l5 5 H120" />
                  </svg>
                </span>
              </div>
            </>
          )}

          <form onSubmit={handleSubmit(submit)} noValidate>
            {isSignup && field("name", "Full name", "text", "name")}
            {mode !== "verify-phone" && field("email", "Email address", "email", "email")}
            {(isSignup || mode === "verify-phone") && phoneField}
            {(isLogin || isSignup) &&
              field("password", "Password", "password", isSignup ? "new-password" : "current-password")}

            {isSignup && (
              <>
                <div
                  className="password-strength"
                  aria-live="polite"
                  aria-label={`Password strength: ${password ? strengthLabels[strength] : "not entered"}`}
                >
                  <div className="strength-bars" aria-hidden="true">
                    {[1, 2, 3, 4].map((n) => (
                      <i key={n} className={strength >= n ? `filled level-${strength}` : ""} />
                    ))}
                  </div>
                  <small>
                    {password
                      ? strengthLabels[strength]
                      : "Use at least 12 characters. A long, unique passphrase is best."}
                  </small>
                </div>
                {field("confirmPassword", "Confirm password", "password", "new-password")}

                <div className="field">
                  <label htmlFor="auth-role">I am a…</label>
                  <div className="select-wrap">
                    <select
                      id="auth-role"
                      {...register("role")}
                      aria-invalid={Boolean(errors.role)}
                      aria-describedby={errors.role ? "auth-role-error" : undefined}
                    >
                      <option value="">Select your role</option>
                      {authRoles.map((role) => (
                        <option key={role}>{role}</option>
                      ))}
                    </select>
                  </div>
                  {errors.role && (
                    <span id="auth-role-error" className="field-error" role="alert">
                      {errors.role.message}
                    </span>
                  )}
                </div>

                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    {...register("consent")}
                    aria-describedby={errors.consent ? "auth-consent-error" : undefined}
                  />
                  <span>
                    I accept the{" "}
                    <button type="button" className="inline-button" onClick={() => setTerms(true)}>
                      prototype terms and privacy notice
                    </button>
                    .
                  </span>
                </label>
                {errors.consent && (
                  <span id="auth-consent-error" className="field-error" role="alert">
                    {errors.consent.message}
                  </span>
                )}
              </>
            )}

            {isVerify && (
              <>
                <OtpInput
                  value={watch("code")}
                  onChange={(value) => setValue("code", value, { shouldValidate: false })}
                  error={errors.code?.message}
                />
                <button
                  type="button"
                  className="text-link resend-button"
                  onClick={resend}
                  disabled={seconds > 0 || providerBusy !== null}
                >
                  {providerBusy === "resend" ? (
                    <LoaderCircle className="spin" size={14} aria-hidden="true" />
                  ) : null}
                  {seconds > 0 ? `Resend available in ${seconds}s` : "Request / resend code"}
                </button>
                <p className="fine-print">
                  No code has been sent. SMS and email verification require a configured provider.
                  The resend cooldown starts only after a provider accepts a delivery request.
                </p>
              </>
            )}

            {isLogin && (
              <Link className="forgot-link" href="/forgot-password">
                Forgot password?
              </Link>
            )}

            {notice && (
              <div className="form-alert" role="alert">
                <ShieldAlert size={16} aria-hidden="true" />
                <span>{notice}</span>
              </div>
            )}

            <button
              type="submit"
              className={`button full-width${succeeded ? " auth-succeeded" : ""}`}
              disabled={isSubmitting || succeeded || providerBusy !== null}
            >
              {succeeded ? (
                <>
                  <Check size={17} aria-hidden="true" />
                  {isSignup ? "Account created" : "Signed in"}
                </>
              ) : isSubmitting ? (
                <>
                  <LoaderCircle className="spin" size={17} aria-hidden="true" />
                  Checking…
                </>
              ) : (
                <>
                  {copy[mode].submit}
                  <ArrowUpRight size={17} aria-hidden="true" />
                </>
              )}
            </button>
          </form>

          <div className="auth-bottom">
            {isLogin ? (
              <p>
                New to RehabSense? <Link href="/signup">Get started</Link>
              </p>
            ) : (
              <Link href="/login" className="text-link">
                <ArrowLeft size={15} aria-hidden="true" />
                Back to sign in
              </Link>
            )}
            <Link href="/dashboard" className="text-link">
              Explore without an account
              <ArrowUpRight size={15} aria-hidden="true" />
            </Link>
          </div>

          <div className="auth-panel-foot">
            <LiteToggle />
            <span className="fine-print">Research prototype · not a medical device</span>
          </div>
        </section>
      </div>

      <Modal open={terms} onClose={() => setTerms(false)} title="Prototype terms & privacy">
        <p>
          This research interface exists to explore RehabSense. It is not a medical service, a
          diagnostic device, or a production account system.
        </p>
        <p>
          Do not enter real passwords or sensitive health information. While no authentication
          adapter is configured, the sign-in and sign-up forms validate locally and your entries
          are never transmitted — the server is only asked whether authentication exists, and it
          answers no.
        </p>
        <p>
          Illustrative dashboard values are not personal medical records. Production terms, a named
          data controller, retention periods, user-rights processes and authentication safeguards
          must be established before any real account or health data is collected.
        </p>
      </Modal>
    </main>
  );
}
