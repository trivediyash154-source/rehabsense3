"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowUpRight, CheckCircle2, LoaderCircle, ShieldAlert } from "lucide-react";
import {
  contactReasons,
  contactRoles,
  contactSchema,
  type ContactValues,
} from "@/lib/validations";
import { track } from "@/lib/analytics";

type Status =
  | { kind: "idle" }
  | { kind: "success" }
  | { kind: "error"; message: string; unconfigured: boolean };

export function ContactForm() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const started = useRef(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ContactValues>({
    resolver: zodResolver(contactSchema),
    defaultValues: {
      // Optional convenience for demos; empty by default in a public deploy.
      name: process.env.NEXT_PUBLIC_CONTACT_PREFILL_NAME ?? "",
      email: "",
      phone: "",
      organization: "",
      message: "",
      website: "",
      reason: "Demonstration",
    },
    mode: "onBlur",
  });

  const submit = async (values: ContactValues) => {
    setStatus({ kind: "idle" });
    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });

      if (!response.ok) {
        const data = (await response.json().catch(() => null)) as
          | { message?: string; code?: string }
          | null;
        setStatus({
          kind: "error",
          message: data?.message ?? "Your message could not be delivered. Please try again.",
          unconfigured: data?.code === "CONTACT_NOT_CONFIGURED",
        });
        track("contact_failed", {
          code: data?.code === "CONTACT_NOT_CONFIGURED"
            ? "CONTACT_NOT_CONFIGURED"
            : "CONTACT_DELIVERY_FAILED",
        });
        return;
      }

      // Only a confirmed 2xx from a configured delivery endpoint reaches here.
      setStatus({ kind: "success" });
      track("contact_submitted", { action: "delivered" });
    } catch {
      setStatus({
        kind: "error",
        message: "We could not reach the server. Your message has not been sent.",
        unconfigured: false,
      });
      track("error_occurred", { code: "CONTACT_DELIVERY_FAILED" });
    }
  };

  if (status.kind === "success") {
    return (
      <div className="contact-success" role="status" tabIndex={-1}>
        <CheckCircle2 size={34} aria-hidden="true" />
        <h3>A conversation starts here.</h3>
        <p>
          Your message has been accepted by the delivery service. The RehabSense team will review
          it and respond using the details you provided.
        </p>
        <button
          type="button"
          className="button button-outline"
          onClick={() => setStatus({ kind: "idle" })}
        >
          Send another message
        </button>
      </div>
    );
  }

  const field = (
    name: "name" | "email" | "phone" | "organization",
    label: string,
    type = "text",
    autoComplete?: string,
  ) => (
    <div className="field">
      <label htmlFor={`contact-${name}`}>{label}</label>
      <input
        id={`contact-${name}`}
        type={type}
        autoComplete={autoComplete}
        {...register(name)}
        aria-invalid={Boolean(errors[name])}
        aria-describedby={errors[name] ? `contact-${name}-error` : undefined}
      />
      {errors[name] && (
        <span id={`contact-${name}-error`} className="field-error" role="alert">
          {errors[name]?.message}
        </span>
      )}
    </div>
  );

  return (
    <form
      className="contact-form"
      onSubmit={handleSubmit(submit)}
      noValidate
      onFocus={() => {
        if (!started.current) {
          track("contact_started");
          started.current = true;
        }
      }}
    >
      <div className="form-grid">
        {field("name", "Full name", "text", "name")}
        {field("email", "Email address", "email", "email")}
        {field("phone", "Contact number · optional", "tel", "tel")}
        {field("organization", "College, clinic or organization", "text", "organization")}

        <div className="field">
          <label htmlFor="contact-role">Your role</label>
          <div className="select-wrap">
            <select
              id="contact-role"
              {...register("role")}
              aria-invalid={Boolean(errors.role)}
              aria-describedby={errors.role ? "contact-role-error" : undefined}
              defaultValue=""
            >
              <option value="" disabled>
                Select your role
              </option>
              {contactRoles.map((role) => (
                <option key={role}>{role}</option>
              ))}
            </select>
          </div>
          {errors.role && (
            <span id="contact-role-error" className="field-error" role="alert">
              {errors.role.message}
            </span>
          )}
        </div>

        <div className="field">
          <label htmlFor="contact-reason">Reason for contacting</label>
          <div className="select-wrap">
            <select
              id="contact-reason"
              {...register("reason")}
              aria-invalid={Boolean(errors.reason)}
              aria-describedby={errors.reason ? "contact-reason-error" : undefined}
            >
              {contactReasons.map((reason) => (
                <option key={reason}>{reason}</option>
              ))}
            </select>
          </div>
          {errors.reason && (
            <span id="contact-reason-error" className="field-error" role="alert">
              {errors.reason.message}
            </span>
          )}
        </div>
      </div>

      <div className="field">
        <label htmlFor="contact-message">What would you like to explore?</label>
        <textarea
          id="contact-message"
          rows={4}
          maxLength={3000}
          placeholder="Tell us about your interest in RehabSense…"
          {...register("message")}
          aria-invalid={Boolean(errors.message)}
          aria-describedby="contact-message-help"
        />
        {errors.message && (
          <span className="field-error" role="alert">
            {errors.message.message}
          </span>
        )}
        <span id="contact-message-help" className="fine-print">
          Please don&apos;t include medical records or sensitive health information.
        </span>
      </div>

      {/* Honeypot. Hidden from assistive tech and from sighted users alike. */}
      <div className="honeypot" aria-hidden="true">
        <label htmlFor="contact-website">Leave this field empty</label>
        <input id="contact-website" tabIndex={-1} autoComplete="off" {...register("website")} />
      </div>

      <label className="checkbox-label">
        <input
          type="checkbox"
          {...register("consent")}
          aria-describedby={errors.consent ? "contact-consent-error" : undefined}
        />
        <span>
          I consent to the team using these details to respond to my enquiry.{" "}
          <Link href="/#responsible">Read the prototype privacy notice.</Link>
        </span>
      </label>
      {errors.consent && (
        <span id="contact-consent-error" className="field-error" role="alert">
          {errors.consent.message}
        </span>
      )}

      {status.kind === "error" && (
        <div className={`form-alert ${status.unconfigured ? "form-alert-info" : ""}`} role="alert">
          <ShieldAlert size={16} aria-hidden="true" />
          <span>
            {status.message}
            {status.unconfigured && (
              <>
                <br />
                <span className="fine-print">
                  Developer note: set <code>CONTACT_DELIVERY_URL</code> (and optionally{" "}
                  <code>CONTACT_DELIVERY_TOKEN</code>) to a trusted HTTPS endpoint to enable
                  delivery. Your entries above have been kept.
                </span>
              </>
            )}
          </span>
        </div>
      )}

      <div className="form-submit">
        <button type="submit" className="button" disabled={isSubmitting}>
          {isSubmitting ? (
            <>
              <LoaderCircle className="spin" size={17} aria-hidden="true" />
              Sending securely…
            </>
          ) : (
            <>
              Start a conversation
              <ArrowUpRight size={18} aria-hidden="true" />
            </>
          )}
        </button>
        <span className="fine-print">
          For demonstrations, research
          <br />
          and thoughtful collaboration.
        </span>
      </div>
    </form>
  );
}
