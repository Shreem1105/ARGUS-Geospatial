import { redirect } from "next/navigation";

export default function LegacyMonitorPage() {
  redirect("/monitors");
}
