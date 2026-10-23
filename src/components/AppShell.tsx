"use client";

import type { ReactNode } from "react";
import type { NotificationItem } from "@/lib/types";
import { DashboardShell } from "./DashboardShell";

/** 로그인한 자녀용 화면 틀 */
export function AppShell({
  children,
  back,
  onNotification,
}: {
  children: ReactNode;
  back?: string;
  onNotification?: (n: NotificationItem) => void;
}) {
  return (
    <DashboardShell back={back} onNotification={onNotification}>{children}</DashboardShell>
  );
}
