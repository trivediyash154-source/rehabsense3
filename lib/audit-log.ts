/**
 * Operational audit trail for integration boundaries.
 *
 * Records outcomes only. No request bodies, credentials, message contents or
 * personal data are ever written here — a record is a fixed action/outcome
 * pair plus a short machine code.
 */

export type AuditRecord = {
  action: "contact_delivery" | "auth_attempt" | "integration_failure" | "rate_limit";
  outcome: "accepted" | "rejected" | "unavailable";
  code: string;
  at: string;
};

export interface AuditAdapter {
  write(record: AuditRecord): Promise<void>;
}

let productionAdapter: AuditAdapter | undefined;

export function configureAuditAdapter(adapter: AuditAdapter) {
  productionAdapter = adapter;
}

export async function audit(
  action: AuditRecord["action"],
  outcome: AuditRecord["outcome"],
  code: string,
) {
  const record: AuditRecord = {
    action,
    outcome,
    code: code.slice(0, 80),
    at: new Date().toISOString(),
  };

  if (process.env.NODE_ENV === "development") {
    console.info("[RehabSense audit]", record);
    return;
  }

  try {
    await productionAdapter?.write(record);
  } catch {
    // Audit transport failure must not surface as a product error.
  }
}
