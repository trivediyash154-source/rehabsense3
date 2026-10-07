"use client";

import { useParams } from "next/navigation";
import { SessionAnalysisView } from "@/components/movement/SessionAnalysisView";
import { Failure } from "@/components/movement/Bits";

export default function SessionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  if (!Number.isFinite(id)) return <Failure error="Not a valid session." />;
  return <SessionAnalysisView sessionId={id} />;
}
