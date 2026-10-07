"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";
import { PatientMovementView } from "@/components/movement/PatientMovementView";
import { Failure } from "@/components/movement/Bits";
import { useData } from "@/lib/api/DataProvider";

export default function PatientDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { patient, selectPatient, patients } = useData();

  // Keep the workspace's record switcher on the record being viewed.
  useEffect(() => {
    if (Number.isFinite(id) && patient?.id !== id && patients.some((p) => p.id === id)) selectPatient(id);
  }, [id, patient?.id, patients, selectPatient]);

  if (!Number.isFinite(id)) return <Failure error="Not a valid record." />;
  return <PatientMovementView patientId={id} variant="detail" />;
}
