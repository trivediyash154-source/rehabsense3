"use client";

import { useCallback, useEffect, useState } from "react";
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
  RefreshCw,
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
  checkApiAvailability,
  homeForRole,
  signIn,
  signUp,
  type ApiAvailability,
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
  // The three modes below have no delivery provider (email or SMS) and no
  // backend endpoint, so their screens state that instead of offering a form.
  "forgot-password": {
    title: "Password reset is not available.",
    description:
      "This prototype has no email provider connected, so it cannot send reset links. If you cannot sign in, contact the team running this RehabSense deployment.",
    submit: "",
  },
  "verify-phone": {
    title: "Phone verification is currently unavailable.",
    description:
      "No SMS provider is connected, so RehabSense never sends or checks phone codes. Email and password sign-in does not need a verified phone number.",
    submit: "",
  },
  "verify-email": {
    title: "Email verification is currently unavailable.",
    description:
      "No email provider is connected, so no verification message is ever sent. Accounts created with email and password work without it.",
    submit: "",
  },
};

export function AuthScreen({ mode }: { mode: AuthMode }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refresh } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState("");
  const [succeeded, setSucceeded] = useState(false);
  const [terms, setTerms] = useState(false);
  const [api, setApi] = useState<ApiAvailability | null>(null);

  const isSignup = mode === "signup";
  const isLogin = mode === "login";
  const hasForm = isLogin || isSignup;
  const notConnected = api?.state === "not-connected";

  const {
    register,
    watch,
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

  // Ask whether the API is reachable before anyone types a password.
  const probeApi = useCallback(async () => {
    setApi(null);
    setApi(await checkApiAvailability());
  }, []);

  useEffect(() => {
    if (hasForm) void probeApi();
  }, [hasForm, probeApi]);

  async function submit(values: AuthValues) {
    setNotice("");
    track(isSignup ? "signup_started" : "login_started", { action: mode });

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
      <label htmlFor="auth-phone">
        Phone number <span className="field-optional">(optional, not verified)</span>
      </label>
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
              {!hasForm ? (
                <>
                  <strong>Research prototype — not configured</strong>
                  <p>
                    Email and SMS delivery are not configured, so no message or code is ever sent
                    from RehabSense. Email and password sign-in does not depend on it.
                  </p>
                </>
              ) : notConnected ? (
                <>
                  <strong>Research prototype — accounts unavailable here</strong>
                  <p>
                    This deployment is not connected to the RehabSense API, so accounts cannot be
                    created or used. Nothing typed on this page is sent anywhere.
                  </p>
                </>
              ) : (
                <>
                  <strong>Research prototype — accounts are real</strong>
                  <p>
                    Email and password sign-in creates a real account on the RehabSense backend:
                    your password is stored only as an Argon2id hash, and the session is held in a
                    cookie no script on this page can read. Social sign-in, phone sign-in and
                    password reset are not available in this prototype.
                  </p>
                </>
              )}
            </div>
          </div>

          <div className="auth-signature" aria-hidden="true">
            <i />
            <i />
            <span />
          </div>

          <h2 id="auth-title">{copy[mode].title}</h2>
          <p className="auth-description">{copy[mode].description}</p>

          {hasForm && api === null && (
            <p className="api-status" role="status">
              <LoaderCircle className="spin" size={14} aria-hidden="true" />
              Checking the connection to the RehabSense API…
            </p>
          )}
          {hasForm && api && api.state !== "available" && (
            <div className="form-alert api-alert" role="alert">
              <ShieldAlert size={16} aria-hidden="true" />
              <span>
                {notConnected
                  ? `${isSignup ? "Sign-up" : "Sign-in"} is unavailable. ${api.message}`
                  : api.message}
              </span>
              {!notConnected && (
                <button type="button" className="text-link" onClick={() => void probeApi()}>
                  <RefreshCw size={14} aria-hidden="true" />
                  Try again
                </button>
              )}
            </div>
          )}

          {hasForm && (
            <form onSubmit={handleSubmit(submit)} noValidate>
              <fieldset className="auth-fieldset" disabled={notConnected || succeeded}>
                {isSignup && field("name", "Full name", "text", "name")}
                {field("email", "Email address", "email", "email")}
                {isSignup && phoneField}
                {field("password", "Password", "password", isSignup ? "new-password" : "current-password")}

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
                  disabled={isSubmitting || succeeded || notConnected}
                >
                  {succeeded ? (
                    <>
                      <Check size={17} aria-hidden="true" />
                      {isSignup ? "Account created" : "Signed in"}
                    </>
                  ) : isSubmitting ? (
                    <>
                      <LoaderCircle className="spin" size={17} aria-hidden="true" />
                      {isSignup ? "Creating account…" : "Signing in…"}
                    </>
                  ) : (
                    <>
                      {copy[mode].submit}
                      <ArrowUpRight size={17} aria-hidden="true" />
                    </>
                  )}
                </button>
              </fieldset>
            </form>
          )}

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
              Explore the illustrative demo
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
          This research interface exists to explore RehabSense. It is not a medical service or a
          diagnostic device.
        </p>
        <p>
          Creating an account sends your name, email address, role and optional phone number to the
          RehabSense API over HTTPS. Your password is stored only as an Argon2id hash, and your
          session is kept in an HttpOnly cookie that page scripts cannot read. Phone numbers are
          stored but never verified, and no email or SMS is ever sent.
        </p>
        <p>
          Do not enter sensitive health information or a password you use elsewhere. Illustrative
          dashboard values are not personal medical records. Production terms, a named data
          controller, retention periods and user-rights processes must be in place before real
          patient data is collected.
        </p>
      </Modal>
    </main>
  );
}
