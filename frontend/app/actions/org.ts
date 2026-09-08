"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export async function switchOrg(orgId: string) {
  const cookieStore = await cookies();
  cookieStore.set("primer_active_org", orgId, { path: "/", maxAge: 60 * 60 * 24 * 365 });
  redirect("/dashboard");
}
