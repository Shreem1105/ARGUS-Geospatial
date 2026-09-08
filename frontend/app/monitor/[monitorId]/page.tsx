import { redirect } from "next/navigation";

type LegacyMonitorDetailPageProps = {
  params: Promise<{ monitorId: string }>;
};

export default async function LegacyMonitorDetailPage({ params }: LegacyMonitorDetailPageProps) {
  const { monitorId } = await params;
  redirect(`/monitors/${monitorId}`);
}
