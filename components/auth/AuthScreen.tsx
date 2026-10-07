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
  oauthErrorMessage,
  oauthStartUrl,
  providerLabel,
  signIn,
  signUp,
  type ApiAvailability,
  type SocialProvider,
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

const SOCIAL: { id: SocialProvider; Mark: () => React.JSX.Element }[] = [
  { id: "google", Mark: GoogleMark },
  { id: "facebook", Mark: FacebookMark },
];

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
  const { setSignedIn } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState("");
  const [succeeded, setSucceeded] = useState(false);
  const [terms, setTerms] = useState(false);
  const [api, setApi] = useState<ApiAvailability | null>(null);
  // Which provider the browser is being sent to, for the button's own state.
  const [redirecting, setRedirecting] = useState<SocialProvider | null>(null);
  // The probe is still running after a couple of seconds: the API is waking.
  const [slowProbe, setSlowProbe] = useState(false);

  const isSignup = mode === "signup";
  const isLogin = mode === "login";
  const hasForm = isLogin || isSignup;
  const notConnected = api?.state === "not-connected";
  const providers = api?.state === "available" ? api.providers : null;

  // A Google/Facebook attempt that came back without signing anyone in.
  const oauthError = searchParams.get("oauth_error");
  const oauthProviderParam = searchParams.get("provider");
  const oauthProvider: SocialProvider | null =
    oauthProviderParam === "google" || oauthProviderParam === "facebook" ? oauthProviderParam : null;
  const linkAfterSignIn = isLogin && oauthError === "account_exists" && oauthProvider !== null;

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
    setSlowProbe(false);
    const slow = setTimeout(() => setSlowProbe(true), 2000);
    try {
      setApi(await checkApiAvailability());
    } finally {
      clearTimeout(slow);
    }
  }, []);

  useEffect(() => {
    if (hasForm) void probeApi();
  }, [hasForm, probeApi]);

  // Coming back with the browser's Back button restores this page from the
  // back/forward cache with the "Redirecting…" state still showing.
  useEffect(() => {
    const reset = (event: PageTransitionEvent) => {
      if (event.persisted) setRedirecting(null);
    };
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  function continueWith(provider: SocialProvider) {
    setNotice("");
    if (providers && !providers[provider]?.enabled) {
      // Never pretend: no redirect, no session, and email sign-in still works.
      setNotice(oauthErrorMessage("not_configured", provider));
      return;
    }
    // Still checking (a waking API can take a few seconds): let the server
    // decide. Its start route either sends the browser to the provider or
    // straight back here with "not configured" -- it never signs anyone in.
    track("social_auth_started", { provider });
    setRedirecting(provider);
    const role = isSignup ? (ROLE_VALUES[watch("role")] ?? null) : null;
    window.location.assign(
      oauthStartUrl(provider, { next: searchParams.get("next"), role: role === "PATIENT" ? null : role }),
    );
  }

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

      // The response already carries the signed-in user and the cookie is
      // set, so the workspace can open straight away: no second /me request
      // and no artificial pause.
      setSucceeded(true);
      setSignedIn(session.user);

      if (linkAfterSignIn && oauthProvider) {
        // Signed in to the existing account: now prove the Google/Facebook
        // side too, and connect it to this account (never by email alone).
        window.location.assign(
          oauthStartUrl(oauthProvider, { intent: "link", next: "/workspace/settings" }),
        );
        return;
      }

      const next = searchParams.get("next");
      const destination =
        next && next.startsWith("/") && !next.startsWith("//")
          ? next
          : homeForRole(session.user.role);
      router.replace(destination);
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
        <AuthStage
          mode={mode}
          methods={
            providers
              ? ["EMAIL", ...SOCIAL.filter(({ id }) => providers[id]?.enabled).map(({ id }) => id.toUpperCase())]
              : undefined
          }
        />

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
                    Every sign-in creates a real session on the RehabSense backend, held in a cookie
                    no script on this page can read. Google and Facebook sign-in happen on their own
                    pages: RehabSense never sees those passwords. Email passwords are stored only as
                    an Argon2id hash. Phone sign-in and password reset are not available.
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
              {slowProbe
                ? "Waking the RehabSense API. After a quiet spell this takes a few seconds…"
                : "Checking the connection to the RehabSense API…"}
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

          {isLogin && searchParams.get("account") === "deleted" && (
            <div className="form-alert form-alert-info" role="status">
              <Check size={16} aria-hidden="true" />
              <span>Your RehabSense account was deleted and you were signed out everywhere.</span>
            </div>
          )}

          {hasForm && oauthError && (
            <div className={`form-alert${oauthError === "cancelled" || linkAfterSignIn ? " form-alert-info" : ""}`}
                 role="alert">
              <ShieldAlert size={16} aria-hidden="true" />
              <span>
                {oauthErrorMessage(oauthError, oauthProvider)}
                {oauthError === "email_required" && oauthProvider === "facebook" && (
                  <>
                    {" "}
                    <a className="inline-button" href={oauthStartUrl("facebook", { rerequest: true })}>
                      Try Facebook again
                    </a>
                  </>
                )}
              </span>
            </div>
          )}

          {hasForm && (
            <form onSubmit={handleSubmit(submit)} noValidate>
              <fieldset className="auth-fieldset" disabled={notConnected || succeeded || redirecting !== null}>
                {isSignup && (
                  <div className="field">
                    <label htmlFor="auth-role">I am a…</label>
                    <div className="select-wrap">
                      <select
                        id="auth-role"
                        {...register("role")}
                        aria-invalid={Boolean(errors.role)}
                        aria-describedby={errors.role ? "auth-role-error" : "auth-role-hint"}
                      >
                        {authRoles.map((role) => (
                          <option key={role}>{role}</option>
                        ))}
                      </select>
                    </div>
                    {errors.role ? (
                      <span id="auth-role-error" className="field-error" role="alert">
                        {errors.role.message}
                      </span>
                    ) : (
                      <small id="auth-role-hint" className="field-hint">
                        Applies to every sign-up option below, including Google and Facebook.
                      </small>
                    )}
                  </div>
                )}

                {!linkAfterSignIn && (
                  <>
                    <div className="social-buttons">
                      {SOCIAL.map(({ id, Mark }) => {
                        const configured = providers?.[id]?.enabled ?? false;
                        return (
                          <button
                            key={id}
                            type="button"
                            className="button button-outline full-width"
                            onClick={() => continueWith(id)}
                            aria-describedby={providers && !configured ? `social-${id}-off` : undefined}
                          >
                            {redirecting === id ? (
                              <LoaderCircle className="spin" size={17} aria-hidden="true" />
                            ) : (
                              <Mark />
                            )}
                            {redirecting === id
                              ? `Redirecting to ${providerLabel[id]}…`
                              : `Continue with ${providerLabel[id]}`}
                            {providers && !configured && (
                              <span className="social-off" id={`social-${id}-off`}>
                                Not configured
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                    {isSignup && (
                      <p className="fine-print social-terms">
                        By continuing with Google or Facebook you accept the{" "}
                        <button type="button" className="inline-button" onClick={() => setTerms(true)}>
                          prototype terms and privacy notice
                        </button>
                        .
                      </p>
                    )}

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
                      {linkAfterSignIn && oauthProvider
                        ? `Sign in and connect ${providerLabel[oauthProvider]}`
                        : copy[mode].submit}
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
          With Google or Facebook, you sign in on that provider&apos;s own page. RehabSense receives
          only your account identifier, name and email address, keeps no Google or Facebook token,
          and never posts anything. You can disconnect a provider or delete your account in
          Settings. See the <Link href="/privacy">privacy notice</Link> for details.
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
