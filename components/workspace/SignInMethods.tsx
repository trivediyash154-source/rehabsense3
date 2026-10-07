"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Check, LoaderCircle, ShieldAlert, Trash2, Unlink } from "lucide-react";
import { SettingsRow, SettingsSection } from "@/components/workspace/SettingsRow";
import { useAuth } from "@/components/auth/AuthProvider";
import {
  AuthError,
  deleteAccount,
  disconnectProvider,
  fetchSignInMethods,
  oauthErrorMessage,
  oauthStartUrl,
  providerLabel,
  type SignInMethods as Methods,
  type SocialProvider,
} from "@/lib/auth";

const SOCIAL: SocialProvider[] = ["google", "facebook"];

/**
 * Settings -> Sign-in methods, and deleting the account.
 *
 * Connecting a provider here is the only way a Google or Facebook account is
 * ever attached to an existing RehabSense account: the person is already
 * signed in to this account and then signs in to the provider too. Nothing is
 * linked because two email addresses happen to match.
 */
export function SignInMethodsSection() {
  const params = useSearchParams();
  const [methods, setMethods] = useState<Methods | null>(null);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<SocialProvider | null>(null);
  const [actionError, setActionError] = useState("");

  const load = useCallback(async () => {
    setLoadError("");
    try {
      setMethods(await fetchSignInMethods());
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load sign-in methods.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const linked = params.get("linked");
  const linkError = params.get("oauth_error");
  const linkProvider = params.get("provider");

  const connectedCount = methods ? methods.identities.length + (methods.password ? 1 : 0) : 0;

  async function disconnect(provider: SocialProvider) {
    setActionError("");
    setBusy(provider);
    try {
      await disconnectProvider(provider);
      setConfirming(null);
      await load();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Could not disconnect.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <SettingsSection
      title="Sign-in methods"
      note="Ways to sign in to this account. A provider is connected only while you are signed in here."
    >
      {(linked === "google" || linked === "facebook") && !linkError && (
        <div className="form-alert form-alert-info" role="status">
          <Check size={16} aria-hidden="true" />
          <span>{providerLabel[linked]} is connected. You can use it to sign in from now on.</span>
        </div>
      )}
      {linkError && (
        <div className="form-alert" role="alert">
          <ShieldAlert size={16} aria-hidden="true" />
          <span>{oauthErrorMessage(linkError, linkProvider)}</span>
        </div>
      )}
      {(loadError || actionError) && (
        <div className="form-alert" role="alert">
          <ShieldAlert size={16} aria-hidden="true" />
          <span>{loadError || actionError}</span>
        </div>
      )}

      <SettingsRow
        label="Email and password"
        description={
          methods && !methods.password
            ? "Not set: this account was created with Google or Facebook and signs in with it."
            : "Sign in with your email address and password."
        }
        control={<span className="set-badge">{methods ? (methods.password ? "Set" : "Not set") : "…"}</span>}
      />

      {SOCIAL.map((provider) => {
        const identity = methods?.identities.find((i) => i.provider === provider);
        const available = methods?.available[provider] ?? false;
        const last = identity !== undefined && connectedCount <= 1;
        return (
          <SettingsRow
            key={provider}
            label={providerLabel[provider]}
            description={
              identity
                ? `Connected${identity.email ? ` as ${identity.email}` : ""}.${last ? " This is your only way to sign in, so it cannot be disconnected." : ""}`
                : available
                  ? `Sign in with your ${providerLabel[provider]} account.`
                  : `${providerLabel[provider]} sign-in is not configured on this deployment.`
            }
            control={
              !methods ? (
                <span className="set-value">…</span>
              ) : identity ? (
                confirming === provider ? (
                  <span className="signin-method">
                    <button type="button" className="button button-outline button-small"
                            disabled={busy !== null} onClick={() => void disconnect(provider)}>
                      {busy === provider ? <LoaderCircle className="spin" size={14} aria-hidden="true" />
                        : <Unlink size={14} aria-hidden="true" />}
                      Confirm disconnect
                    </button>
                    <button type="button" className="text-link" onClick={() => setConfirming(null)}>
                      Keep
                    </button>
                  </span>
                ) : (
                  <button type="button" className="button button-outline button-small"
                          disabled={last || busy !== null} onClick={() => setConfirming(provider)}>
                    <Unlink size={14} aria-hidden="true" /> Disconnect
                  </button>
                )
              ) : available ? (
                <a className="button button-outline button-small"
                   href={oauthStartUrl(provider, { intent: "link", next: "/workspace/settings" })}>
                  Connect {providerLabel[provider]}
                </a>
              ) : (
                <span className="set-badge">Not configured</span>
              )
            }
          />
        );
      })}

      <SettingsRow
        label="Phone"
        description="No SMS provider is connected, so phone sign-in is not available."
        control={<span className="set-badge">Not available</span>}
      />
    </SettingsSection>
  );
}

export function DeleteAccountSection() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [password, setPassword] = useState("");
  const [hasPassword, setHasPassword] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!open || hasPassword !== null) return;
    fetchSignInMethods()
      .then((m) => setHasPassword(m.password))
      .catch(() => setHasPassword(true));
  }, [open, hasPassword]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setDeleting(true);
    try {
      await deleteAccount(confirm, hasPassword ? password : undefined);
      // The server cleared the session cookies; start from a clean page.
      window.location.assign("/login?account=deleted");
    } catch (cause) {
      setError(cause instanceof AuthError ? cause.message : "The account was not deleted.");
      setDeleting(false);
    }
  }

  return (
    <div className="danger-zone">
      <SettingsSection
        title="Delete account"
        note="Permanent. There is no undo and no recovery."
      >
        <SettingsRow
          label="Delete this account"
          description="Deletes your RehabSense account, its connected Google and Facebook sign-ins, your profile and notifications, and signs you out everywhere. A patient record that a clinician created stays with that clinician, no longer linked to you."
          control={
            !open ? (
              <button type="button" className="button button-outline button-small"
                      onClick={() => setOpen(true)} disabled={!user}>
                <Trash2 size={14} aria-hidden="true" /> Delete account…
              </button>
            ) : null
          }
        />
        {open && (
          <form className="delete-account-form" onSubmit={submit}>
            <label htmlFor="delete-confirm">Type DELETE to confirm</label>
            <input id="delete-confirm" value={confirm} autoComplete="off"
                   onChange={(e) => setConfirm(e.target.value)} />
            {hasPassword && (
              <>
                <label htmlFor="delete-password">Your password</label>
                <input id="delete-password" type="password" value={password}
                       autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
              </>
            )}
            {error && (
              <div className="form-alert" role="alert">
                <ShieldAlert size={16} aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}
            <span className="signin-method">
              <button type="submit" className="button button-outline button-small"
                      disabled={deleting || confirm.trim() !== "DELETE" || (hasPassword === true && !password)}>
                {deleting ? <LoaderCircle className="spin" size={14} aria-hidden="true" />
                  : <Trash2 size={14} aria-hidden="true" />}
                Permanently delete my account
              </button>
              <button type="button" className="text-link" onClick={() => setOpen(false)}>
                Cancel
              </button>
            </span>
          </form>
        )}
      </SettingsSection>
    </div>
  );
}
